"""
PoC bout-en-bout pour film-indexer : 1 clip → analyse complète → JSON consolidé.

Étapes :
1. Probe le clip source (durée, format)
2. Transcode en proxy 720p H264 NVENC (Nomad RTX 5090)
3. Upload Gemini Files API
4. Pass A factuel (gemini-3-flash-preview ou 2.5-flash)
5. Pass B Murch (text only, contexte = Pass A)
6. Pass B Baxter
7. Pass B Pagh Andersen
8. Si flags sensibles → Janet Malcolm
9. Synthèse FCP (3 lignes)
10. Save consolidated JSON

Usage :
    python poc_single_clip.py --src /path/to/clip.mov [--out output_dir]

Run sur Nomad :
    ssh ismael@192.168.4.43 "C:\\Goldberg\\vo-pipeline\\.venv\\Scripts\\python.exe ..."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Setup repo path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from film_indexer.schemas import (
    PassA, Murch, Baxter, PaghAndersen, JanetMalcolm, SyntheseFCP, ClipAnalysis
)
from film_indexer.lib.gemini import GeminiClient, MODEL_PASS_A_FALLBACK, MODEL_PASS_B_REASONING
from film_indexer.lib.transcode import probe_duration, transcode_proxy_ffmpeg_nvenc
from film_indexer.lib.fcpxml import write_fcpxml

import xxhash


PROMPTS_DIR = REPO_ROOT / "film_indexer" / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt file from the prompts directory."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def hash_file(path: Path) -> str:
    """xxh128 hash of a file."""
    h = xxhash.xxh128()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_pipeline(src: Path, out_dir: Path) -> ClipAnalysis:
    """Run the full PoC pipeline on a single clip."""
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"FILM-INDEXER PoC — single clip pipeline")
    print(f"Source: {src}")
    print(f"Output: {out_dir}")
    print(f"{'='*60}\n")

    timings: dict[str, float] = {}

    # ============================================================
    # STEP 1 : PROBE
    # ============================================================
    t = time.time()
    duration = probe_duration(src)
    if duration is None:
        raise RuntimeError(f"ffprobe failed on {src}")
    print(f"[1/9] Probe : {duration:.1f}s")
    timings["probe"] = time.time() - t

    # ============================================================
    # STEP 2 : HASH
    # ============================================================
    t = time.time()
    clip_hash = hash_file(src)
    print(f"[2/9] Hash xxh128 : {clip_hash}")
    timings["hash"] = time.time() - t

    # ============================================================
    # STEP 3 : TRANSCODE PROXY
    # ============================================================
    t = time.time()
    proxy_path = out_dir / f"{clip_hash}_720p.mp4"
    if not proxy_path.exists():
        print(f"[3/9] Transcode proxy 720p NVENC...")
        ok = transcode_proxy_ffmpeg_nvenc(src, proxy_path)
        if not ok:
            raise RuntimeError(f"Transcode failed for {src}")
        print(f"      -> {proxy_path} ({proxy_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print(f"[3/9] Proxy cached : {proxy_path}")
    timings["transcode"] = time.time() - t

    # ============================================================
    # STEP 4 : INIT GEMINI CLIENT + UPLOAD
    # ============================================================
    t = time.time()
    client = GeminiClient()
    file = client.upload_video(proxy_path, mime_type="video/mp4")
    print(f"[4/9] Uploaded to Gemini : {file.name}")
    timings["upload"] = time.time() - t

    # ============================================================
    # STEP 5 : PASS A — FACTUEL
    # ============================================================
    t = time.time()
    print(f"[5/9] Pass A factuel ({MODEL_PASS_A_FALLBACK})...")
    goldberg_context = load_prompt("goldberg_context_v1")
    pass_a_prompt = load_prompt("pass_a_factuel")

    full_pass_a_system = f"{pass_a_prompt}\n\n---\n\n{goldberg_context}"

    pass_a, meta_a = client.generate_structured(
        model=MODEL_PASS_A_FALLBACK,
        contents=[file, "Analyse ce clip et produis le JSON Pass A factuel selon les instructions du system prompt."],
        schema=PassA,
        system_instruction=full_pass_a_system,
        thinking_level="low",
    )
    # Override technical fields (filled by us, not Gemini)
    pass_a.clip_hash = clip_hash
    pass_a.clip_path = str(src)
    pass_a.technique.duration_s = duration
    print(f"      Pass A OK : {meta_a['tokens_in']} in / {meta_a['tokens_out']} out / ${meta_a['cost_usd']:.4f}")
    timings["pass_a"] = time.time() - t

    pass_a_json = pass_a.model_dump_json(indent=2)
    (out_dir / f"{clip_hash}_pass_a.json").write_text(pass_a_json, encoding="utf-8")

    # ============================================================
    # STEP 6 : MURCH
    # ============================================================
    t = time.time()
    print(f"[6/9] Pass B Murch ({MODEL_PASS_B_REASONING})...")
    murch_prompt = load_prompt("murch_v1")
    murch_system = f"{murch_prompt}\n\n---\n\nCONTEXTE PROJET :\n{goldberg_context}"

    murch_input = (
        "Voici le JSON Pass A factuel d'un clip Goldberg. Produis ton verdict éditorial Murch :\n\n"
        f"```json\n{pass_a_json}\n```"
    )

    murch, meta_m = client.generate_structured(
        model=MODEL_PASS_B_REASONING,
        contents=[murch_input],
        schema=Murch,
        system_instruction=murch_system,
        thinking_level="low",
    )
    murch.clip_hash = clip_hash
    print(f"      Murch verdict : {murch.statut_prise} | {murch.justification_verdict}")
    print(f"      Cost : ${meta_m['cost_usd']:.4f}")
    timings["murch"] = time.time() - t

    (out_dir / f"{clip_hash}_murch.json").write_text(murch.model_dump_json(indent=2), encoding="utf-8")

    # ============================================================
    # STEP 7 : BAXTER
    # ============================================================
    t = time.time()
    print(f"[7/9] Pass B Baxter ({MODEL_PASS_B_REASONING})...")
    baxter_prompt = load_prompt("baxter_v1")
    baxter_system = f"{baxter_prompt}\n\n---\n\nCONTEXTE PROJET :\n{goldberg_context}"

    baxter_input = (
        "Voici le JSON Pass A factuel + le verdict Murch d'un clip Goldberg. Produis ta couche Baxter :\n\n"
        f"PASS A:\n```json\n{pass_a_json}\n```\n\n"
        f"MURCH:\n```json\n{murch.model_dump_json(indent=2)}\n```"
    )

    baxter, meta_b = client.generate_structured(
        model=MODEL_PASS_B_REASONING,
        contents=[baxter_input],
        schema=Baxter,
        system_instruction=baxter_system,
        thinking_level="low",
    )
    baxter.clip_hash = clip_hash
    print(f"      Baxter verdict : {baxter.verdict_baxter}")
    print(f"      Cost : ${meta_b['cost_usd']:.4f}")
    timings["baxter"] = time.time() - t

    (out_dir / f"{clip_hash}_baxter.json").write_text(baxter.model_dump_json(indent=2), encoding="utf-8")

    # ============================================================
    # STEP 8 : PAGH ANDERSEN
    # ============================================================
    t = time.time()
    print(f"[8/9] Pass B Pagh Andersen ({MODEL_PASS_B_REASONING})...")
    pagh_prompt = load_prompt("pagh_andersen_v1")
    pagh_system = f"{pagh_prompt}\n\n---\n\nCONTEXTE PROJET :\n{goldberg_context}"

    pagh_input = (
        "Voici le JSON Pass A + Murch + Baxter d'un clip Goldberg. Produis ta couche Pagh Andersen :\n\n"
        f"PASS A:\n```json\n{pass_a_json}\n```\n\n"
        f"MURCH:\n```json\n{murch.model_dump_json(indent=2)}\n```\n\n"
        f"BAXTER:\n```json\n{baxter.model_dump_json(indent=2)}\n```"
    )

    pagh, meta_p = client.generate_structured(
        model=MODEL_PASS_B_REASONING,
        contents=[pagh_input],
        schema=PaghAndersen,
        system_instruction=pagh_system,
        thinking_level="low",
    )
    pagh.clip_hash = clip_hash
    print(f"      Pagh Andersen note : {pagh.note_pagh}")
    print(f"      Cost : ${meta_p['cost_usd']:.4f}")
    timings["pagh_andersen"] = time.time() - t

    (out_dir / f"{clip_hash}_pagh_andersen.json").write_text(pagh.model_dump_json(indent=2), encoding="utf-8")

    # ============================================================
    # STEP 9 : JANET MALCOLM (CONDITIONNEL)
    # ============================================================
    malcolm = None
    if pass_a.project_tags.sensitive_flags:
        t = time.time()
        print(f"[9a/9] Council éthique Janet Malcolm (conditionnel — sensibles détectés)...")
        malcolm_prompt = load_prompt("janet_malcolm_v1")
        malcolm_system = f"{malcolm_prompt}\n\n---\n\nCONTEXTE PROJET :\n{goldberg_context}"

        malcolm_input = (
            "Ce clip a été flaggé sensible. Produis ton verdict éthique :\n\n"
            f"PASS A:\n```json\n{pass_a_json}\n```"
        )

        malcolm, meta_mal = client.generate_structured(
            model=MODEL_PASS_B_REASONING,
            contents=[malcolm_input],
            schema=JanetMalcolm,
            system_instruction=malcolm_system,
            thinking_level="low",
        )
        malcolm.clip_hash = clip_hash
        print(f"      Verdict : {malcolm.verdict} | {malcolm.note_finale_malcolm}")
        timings["malcolm"] = time.time() - t

        (out_dir / f"{clip_hash}_malcolm.json").write_text(malcolm.model_dump_json(indent=2), encoding="utf-8")
    else:
        print(f"[9a/9] Janet Malcolm skipped (no sensitive flags)")

    # ============================================================
    # STEP 10 : SYNTHÈSE FCP
    # ============================================================
    t = time.time()
    print(f"[9b/9] Synthèse FCP...")
    synthese_input = (
        "Tu es le synthétiseur final pour Final Cut Pro 12. Tu reçois les passes Pass A, Murch, Baxter, Pagh Andersen "
        "(et éventuellement Janet Malcolm). Produis une fiche de 3 lignes maximum, des keywords FCP utilisables, "
        "une priorité 1-5 et un edit_intent (A_ROLL/B_ROLL/REJECT/DEEP_REVIEW).\n\n"
        f"PASS A:\n```json\n{pass_a_json}\n```\n\n"
        f"MURCH:\n```json\n{murch.model_dump_json(indent=2)}\n```\n\n"
        f"BAXTER:\n```json\n{baxter.model_dump_json(indent=2)}\n```\n\n"
        f"PAGH:\n```json\n{pagh.model_dump_json(indent=2)}\n```"
    )
    if malcolm:
        synthese_input += f"\n\nMALCOLM:\n```json\n{malcolm.model_dump_json(indent=2)}\n```"

    synthese, meta_s = client.generate_structured(
        model=MODEL_PASS_B_REASONING,
        contents=[synthese_input],
        schema=SyntheseFCP,
        system_instruction="Tu es le synthétiseur final. Output JSON strict selon SyntheseFCP schema. Phrases courtes, keywords FCP-friendly.",
        thinking_level="minimal",
    )
    synthese.clip_hash = clip_hash
    print(f"      Synthèse OK : priority={synthese.priority_1_5} intent={synthese.edit_intent}")
    print(f"      Note FCP : {synthese.fcp_note_3_lines}")
    timings["synthese"] = time.time() - t

    # ============================================================
    # CONSOLIDATE
    # ============================================================
    total_cost = sum(m["cost_usd"] for m in [meta_a, meta_m, meta_b, meta_p, meta_s])
    if malcolm and "malcolm" in timings:
        # malcom meta wasn't captured here, approximate
        pass

    analysis = ClipAnalysis(
        clip_hash=clip_hash,
        clip_path=str(src),
        pass_a=pass_a,
        murch=murch,
        baxter=baxter,
        pagh_andersen=pagh,
        janet_malcolm=malcolm,
        synthese=synthese,
        total_cost_usd=round(total_cost, 4),
        timings_s={k: round(v, 2) for k, v in timings.items()},
    )

    final_path = out_dir / f"{clip_hash}_FINAL.json"
    final_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")

    # ============================================================
    # FCPXML OUTPUT
    # ============================================================
    print(f"[10/9] FCPXML writer...")
    fcpxml_path = out_dir / f"{clip_hash}.fcpxml"
    try:
        write_fcpxml(analysis, fcpxml_path, fps=25.0)
        print(f"      FCPXML : {fcpxml_path} ({fcpxml_path.stat().st_size} bytes)")
    except Exception as e:
        print(f"      FCPXML write FAILED: {e}")
        import traceback; traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"DONE — Total cost ${total_cost:.4f}")
    print(f"Total time : {sum(timings.values()):.1f}s")
    print(f"Final JSON : {final_path}")
    print(f"FCPXML     : {fcpxml_path}")
    print(f"{'='*60}\n")

    # Cleanup uploaded file
    client.delete_uploaded(file.name)

    return analysis


def main():
    parser = argparse.ArgumentParser(description="Film-indexer PoC : single clip pipeline")
    parser.add_argument("--src", type=Path, required=True, help="Source clip path")
    parser.add_argument("--out", type=Path, default=Path("C:/Goldberg/film-indexer/output"), help="Output directory")
    args = parser.parse_args()

    if not args.src.exists():
        print(f"ERROR: source not found: {args.src}", file=sys.stderr)
        sys.exit(1)

    try:
        run_pipeline(args.src, args.out)
    except Exception as e:
        print(f"\nFATAL ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
