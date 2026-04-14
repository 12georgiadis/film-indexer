"""
FCPXML writer pour film-indexer.

Génère un FCPXML 1.13 standalone contenant un ou plusieurs asset-clips
avec leurs keywords + markers + custom metadata depuis les ClipAnalysis.

Pattern Lumberyard : on PATCHE un FCPXML existant exporté de FCP 12,
plutôt que de générer from-scratch (plus robuste, IDs préservés).

Pour le PoC : on génère un FCPXML standalone d'un seul clip pour validation.

Rational timecodes : tous les timecodes en fractions XX/YY (jamais en décimal).
Format frame_duration standard :
- 23.976fps → 1001/24000s
- 24fps     → 100/2400s
- 25fps     → 100/2500s
- 29.97fps  → 1001/30000s
- 30fps     → 100/3000s
- 50fps     → 100/5000s
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Optional

from lxml import etree


# ============================================================
# RATIONAL TIMECODE HELPERS
# ============================================================


FRAME_DURATIONS = {
    23.976: "1001/24000s",
    24.0: "100/2400s",
    25.0: "100/2500s",
    29.97: "1001/30000s",
    30.0: "100/3000s",
    48.0: "100/4800s",
    50.0: "100/5000s",
    59.94: "1001/60000s",
    60.0: "100/6000s",
}


def get_frame_duration(fps: float) -> str:
    """Return the FCPXML frame duration string for a given fps."""
    closest = min(FRAME_DURATIONS.keys(), key=lambda f: abs(f - fps))
    return FRAME_DURATIONS[closest]


def seconds_to_rational(seconds: float, fps: float = 25.0) -> str:
    """Convert decimal seconds to FCPXML rational timecode string.

    Examples (fps=25):
        0.0  -> "0s"
        1.0  -> "2500/2500s"
        11.2 -> "28000/2500s"
    """
    if seconds <= 0:
        return "0s"
    # Use timebase = denominator from frame duration
    fd = get_frame_duration(fps)
    # parse "100/2500s" -> denominator = 2500
    if "/" in fd:
        num_str, denom_with_s = fd.split("/")
        denom = int(denom_with_s.rstrip("s"))
        num = int(round(seconds * denom))
        return f"{num}/{denom}s"
    return f"{int(round(seconds))}s"


def parse_timecode_to_seconds(tc: str) -> float:
    """Parse 'MM:SS.cc' or 'HH:MM:SS.cc' to seconds."""
    if not tc or tc == "00:00:00":
        return 0.0
    parts = tc.replace(",", ".").split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(parts[0])


# ============================================================
# FCPXML BUILDER
# ============================================================


def build_fcpxml_standalone(
    analysis,  # ClipAnalysis
    fps: float = 25.0,
) -> str:
    """Build a standalone FCPXML 1.13 document from a ClipAnalysis.

    Contains:
    - <resources> with format and asset
    - <library> > <event> > <asset-clip> with keywords + markers + notes

    Returns the FCPXML as a string.
    """
    duration_s = analysis.pass_a.technique.duration_s or 1.0
    frame_duration = get_frame_duration(fps)
    duration_rational = seconds_to_rational(duration_s, fps)

    # Generate IDs
    format_id = "r1"
    asset_id = "r2"
    clip_name = Path(analysis.clip_path).stem if analysis.clip_path else analysis.clip_hash[:12]
    event_name = "Film Indexer Output"

    # Root element
    fcpxml = etree.Element("fcpxml", version="1.13")

    # Resources
    resources = etree.SubElement(fcpxml, "resources")
    format_el = etree.SubElement(resources, "format",
        id=format_id,
        name="FFVideoFormat1080p25",
        frameDuration=frame_duration,
        width="1920",
        height="1080",
        colorSpace="1-1-1 (Rec. 709)",
    )
    asset_el = etree.SubElement(resources, "asset",
        id=asset_id,
        name=clip_name,
        start="0s",
        duration=duration_rational,
        format=format_id,
        hasVideo="1",
        hasAudio="1",
        videoSources="1",
        audioSources="1",
        audioChannels="2",
    )
    media_rep = etree.SubElement(asset_el, "media-rep",
        kind="original-media",
        src=Path(analysis.clip_path).as_uri() if analysis.clip_path else f"file:///{analysis.clip_hash}.mov",
    )

    # Library / event / asset-clip
    library = etree.SubElement(fcpxml, "library")
    event = etree.SubElement(library, "event", name=event_name)

    # FCP note from synthese (3 lines max)
    note_text = ""
    if analysis.synthese:
        note_text = analysis.synthese.fcp_note_3_lines

    asset_clip = etree.SubElement(event, "asset-clip",
        ref=asset_id,
        offset="0s",
        name=clip_name,
        start="0s",
        duration=duration_rational,
        format=format_id,
        tcFormat="NDF",
        note=note_text,
    )

    # ============================================================
    # KEYWORDS (from synthese.keywords + project tags)
    # ============================================================
    keywords_added = set()

    if analysis.synthese:
        for kw in analysis.synthese.keywords:
            if kw and kw not in keywords_added:
                kw_el = etree.SubElement(asset_clip, "keyword",
                    start="0s",
                    duration=duration_rational,
                    value=kw.lstrip("#"),
                )
                keywords_added.add(kw)

    # Project tags
    pt = analysis.pass_a.project_tags
    for persona in pt.personas_detected:
        if persona not in keywords_added:
            etree.SubElement(asset_clip, "keyword",
                start="0s", duration=duration_rational, value=persona)
            keywords_added.add(persona)
    for theme in pt.themes_detected:
        if theme not in keywords_added:
            etree.SubElement(asset_clip, "keyword",
                start="0s", duration=duration_rational, value=theme)
            keywords_added.add(theme)
    for sf in pt.sensitive_flags:
        if sf not in keywords_added:
            etree.SubElement(asset_clip, "keyword",
                start="0s", duration=duration_rational, value=sf)
            keywords_added.add(sf)

    # ============================================================
    # MARKERS (from Murch moment_cle, Baxter blink, Pagh drop)
    # ============================================================
    if analysis.murch and analysis.murch.moment_cle:
        mc = analysis.murch.moment_cle
        if mc.timecode and mc.nature != "aucun":
            tc_seconds = parse_timecode_to_seconds(mc.timecode)
            if 0 <= tc_seconds < duration_s:
                etree.SubElement(asset_clip, "marker",
                    start=seconds_to_rational(tc_seconds, fps),
                    duration=seconds_to_rational(0.1, fps),
                    value=f"⭐ MOMENT D'OR ({mc.nature}): {mc.raison}"[:200],
                )

    if analysis.baxter and analysis.baxter.blink_analysis:
        ba = analysis.baxter.blink_analysis
        for cut_range in ba.cut_points_estimes:
            # Ranges are "00:14.20-00:14.80"
            if "-" in cut_range:
                start_tc, end_tc = cut_range.split("-")
                tc_start = parse_timecode_to_seconds(start_tc)
                if 0 <= tc_start < duration_s:
                    etree.SubElement(asset_clip, "marker",
                        start=seconds_to_rational(tc_start, fps),
                        duration=seconds_to_rational(0.1, fps),
                        value=f"✂️ Baxter cut ({ba.proxy_utilise or 'unknown'})"[:200],
                    )

    if analysis.pagh_andersen and analysis.pagh_andersen.drop_moment_timecode:
        tc = analysis.pagh_andersen.drop_moment_timecode
        tc_seconds = parse_timecode_to_seconds(tc)
        if 0 <= tc_seconds < duration_s:
            etree.SubElement(asset_clip, "marker",
                start=seconds_to_rational(tc_seconds, fps),
                duration=seconds_to_rational(0.1, fps),
                value=f"🎭 DROP Joshua: {analysis.pagh_andersen.drop_moment_description or ''}"[:200],
            )

    # ============================================================
    # CUSTOM METADATA (md fields for FCP inspector)
    # ============================================================
    if analysis.murch:
        etree.SubElement(asset_clip, "metadata-key",
            key="com.ismael.murch.statut",
            value=analysis.murch.statut_prise,
        ) if False else None  # FCPXML md fields are complex, skip for PoC

    # Serialize
    etree.indent(fcpxml, space="    ")
    xml_string = etree.tostring(
        fcpxml,
        pretty_print=True,
        xml_declaration=True,
        encoding="UTF-8",
        doctype='<!DOCTYPE fcpxml>',
    ).decode("utf-8")

    return xml_string


def write_fcpxml(analysis, output_path: Path, fps: float = 25.0) -> Path:
    """Write a standalone FCPXML for a single ClipAnalysis."""
    xml = build_fcpxml_standalone(analysis, fps=fps)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    return output_path
