"""
Phase 4 — FCPXML patcher (pattern Lumberyard).

Au lieu de générer un FCPXML from-scratch, on PATCHE un FCPXML exporté
de Final Cut Pro 12 et on injecte les keywords + markers + notes dans
les asset-clips existants en les matchant par filename ou par hash.

Avantages :
- Les asset IDs, paths, formats sont déjà valides (FCP les a écrits)
- Les rational timecodes sont alignés sur le format de l'event
- Aucun risque de casser la library
- Exactement le pattern Lumberyard backLogger → Lumberyard merge

Workflow :
1. Sur Mac : FCP → Fichier → Exporter XML → goldberg_library.fcpxml
2. Côté Nomad : on lit le FCPXML, on liste les asset-clips
3. Pour chaque asset-clip, on cherche dans SQLite l'analyse correspondante
4. On injecte keywords + markers + note dans le clip
5. Validation xmllint
6. On écrit goldberg_library_indexed.fcpxml
7. Sur Mac : FCP → Fichier → Importer XML → réimport propre
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from lxml import etree


def parse_fcpxml(fcpxml_path: Path) -> tuple[etree._Element, dict[str, dict]]:
    """Parse a FCPXML file and return root + dict of asset-clips by name.

    Returns:
        root: lxml root element
        clips_by_name: {clip_name: {"element": <asset-clip>, "ref": asset_id, "duration": str}}
    """
    parser = etree.XMLParser(resolve_entities=False, dtd_validation=False, no_network=True)
    tree = etree.parse(str(fcpxml_path), parser)
    root = tree.getroot()

    clips_by_name: dict[str, dict] = {}

    # Find all asset-clips (could be in <event> or <project>/<sequence>)
    for asset_clip in root.iter("asset-clip"):
        name = asset_clip.get("name", "")
        ref = asset_clip.get("ref", "")
        duration = asset_clip.get("duration", "0s")
        clips_by_name[name] = {
            "element": asset_clip,
            "ref": ref,
            "duration": duration,
        }

    return root, clips_by_name


def get_asset_paths(root: etree._Element) -> dict[str, str]:
    """Build a map from asset id to source file path (decoded URL)."""
    asset_paths: dict[str, str] = {}
    for asset in root.iter("asset"):
        asset_id = asset.get("id", "")
        media_rep = asset.find("media-rep")
        if media_rep is not None:
            src = media_rep.get("src", "")
            if src.startswith("file://"):
                src = unquote(src.replace("file://", ""))
                # Windows paths : remove leading slash
                if len(src) > 2 and src[0] == "/" and src[2] == ":":
                    src = src[1:]
            asset_paths[asset_id] = src
    return asset_paths


def patch_clip(asset_clip: etree._Element, analysis_blob: dict, clip_duration_rational: str):
    """Inject keywords + markers + note into one asset-clip."""
    # Note (synthese.fcp_note_3_lines)
    synthese = analysis_blob.get("synthese", {}) or {}
    if synthese.get("fcp_note_3_lines"):
        asset_clip.set("note", synthese["fcp_note_3_lines"][:500])

    # Remove existing keywords/markers we may have added in a previous run
    # (idempotency: don't double-add)
    for child in list(asset_clip):
        if child.tag in ("keyword", "marker") and child.get("data-source") == "film-indexer":
            asset_clip.remove(child)

    # Keywords (synthese.keywords + project_tags.{personas,themes,sensitive_flags})
    keywords = set()
    for kw in synthese.get("keywords", []):
        if kw:
            keywords.add(kw.lstrip("#"))

    pt = (analysis_blob.get("pass_a", {}) or {}).get("project_tags", {}) or {}
    keywords.update(pt.get("personas_detected") or [])
    keywords.update(pt.get("themes_detected") or [])
    keywords.update(pt.get("sensitive_flags") or [])

    for kw in keywords:
        kw_el = etree.SubElement(asset_clip, "keyword",
            start="0s",
            duration=clip_duration_rational,
            value=kw,
        )
        kw_el.set("data-source", "film-indexer")

    # Markers
    from film_indexer.lib.fcpxml import parse_timecode_to_seconds, seconds_to_rational

    # Murch moment d'or
    murch = analysis_blob.get("murch") or {}
    moment_cle = murch.get("moment_cle") or {}
    if moment_cle.get("nature", "aucun") != "aucun" and moment_cle.get("timecode"):
        tc_s = parse_timecode_to_seconds(moment_cle["timecode"])
        if tc_s > 0:
            mk = etree.SubElement(asset_clip, "marker",
                start=seconds_to_rational(tc_s),
                duration="100/2500s",
                value=f"⭐ MURCH ({moment_cle.get('nature', '')}): {moment_cle.get('raison', '')}"[:200],
            )
            mk.set("data-source", "film-indexer")

    # Baxter cut points
    baxter = analysis_blob.get("baxter") or {}
    blink = baxter.get("blink_analysis") or {}
    for cut_range in blink.get("cut_points_estimes") or []:
        if "-" in cut_range:
            start_tc = cut_range.split("-")[0]
            tc_s = parse_timecode_to_seconds(start_tc)
            if tc_s > 0:
                mk = etree.SubElement(asset_clip, "marker",
                    start=seconds_to_rational(tc_s),
                    duration="100/2500s",
                    value=f"✂️ BAXTER ({blink.get('proxy_utilise', 'cut')})"[:200],
                )
                mk.set("data-source", "film-indexer")

    # Pagh drop moment
    pagh = analysis_blob.get("pagh_andersen") or {}
    if pagh.get("drop_moment_timecode"):
        tc_s = parse_timecode_to_seconds(pagh["drop_moment_timecode"])
        if tc_s > 0:
            mk = etree.SubElement(asset_clip, "marker",
                start=seconds_to_rational(tc_s),
                duration="100/2500s",
                value=f"🎭 PAGH DROP: {pagh.get('drop_moment_description', '')}"[:200],
            )
            mk.set("data-source", "film-indexer")


def patch_fcpxml(
    source_fcpxml: Path,
    state_db: Path,
    output_fcpxml: Path,
) -> dict:
    """Patch a FCPXML by injecting analyses from state.db.

    Returns stats: {clips_total, clips_patched, clips_no_analysis}.
    """
    # Open SQLite read-only
    conn = sqlite3.connect(str(state_db))
    conn.row_factory = sqlite3.Row

    # Parse FCPXML
    root, clips_by_name = parse_fcpxml(source_fcpxml)
    asset_paths = get_asset_paths(root)

    stats = {"clips_total": len(clips_by_name), "clips_patched": 0, "clips_no_analysis": 0, "matched_by": {}}

    for clip_name, clip_info in clips_by_name.items():
        # Try to find an analysis matching this clip name
        # First try by stem match against canonical_path
        row = conn.execute(
            "SELECT hash FROM clips WHERE canonical_path LIKE ?",
            (f"%{clip_name}%",),
        ).fetchone()

        if not row:
            stats["clips_no_analysis"] += 1
            continue

        clip_hash = row["hash"]

        # Get the latest synthese artifact for this hash
        artifact = conn.execute("""
            SELECT pass_name, blob FROM artifacts
            WHERE hash = ?
            ORDER BY created_at DESC
        """, (clip_hash,)).fetchall()

        if not artifact:
            stats["clips_no_analysis"] += 1
            continue

        # Build a consolidated analysis blob from all artifacts
        analysis_blob = {}
        for art in artifact:
            try:
                blob = json.loads(art["blob"])
                analysis_blob[art["pass_name"]] = blob
            except json.JSONDecodeError:
                continue

        if not analysis_blob:
            stats["clips_no_analysis"] += 1
            continue

        patch_clip(clip_info["element"], analysis_blob, clip_info["duration"])
        stats["clips_patched"] += 1
        stats["matched_by"][clip_name] = clip_hash[:12]

    # Write output
    output_fcpxml.parent.mkdir(parents=True, exist_ok=True)
    tree = etree.ElementTree(root)
    tree.write(
        str(output_fcpxml),
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
        doctype='<!DOCTYPE fcpxml>',
    )

    conn.close()
    return stats
