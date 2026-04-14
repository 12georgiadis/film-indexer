"""
async_pipeline.py — Vrai orchestrateur async pour batch scaling.

Remplace batch_run.py avec du vrai async (pas de ThreadPoolExecutor serializing).

Architecture :
- asyncio.Semaphore(N) limite le nombre de clips processés simultanément
- Pour chaque clip : Pass A séquentiel, puis Pass B Murch+Baxter+Pagh en asyncio.gather()
- Upload/transcode restent sync (I/O bound, pas de gain async)
- Cost tracking continu dans SQLite

Usage :
    python async_pipeline.py --db state.db --limit 20 --workers 6 --budget-cap 30.0
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

import xxhash

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from film_indexer.schemas import (
    PassA, Murch, Baxter, PaghAndersen, JanetMalcolm, SyntheseFCP, ClipAnalysis
)
from film_indexer.lib.gemini import GeminiClient, MODEL_PASS_A_FALLBACK, MODEL_PASS_B_REASONING
from film_indexer.lib.transcode import probe_duration, transcode_proxy_ffmpeg_nvenc
from film_indexer.lib.fcpxml import write_fcpxml
from film_indexer.state.db import State


PROMPTS_DIR = REPO_ROOT / "film_indexer" / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def hash_file(path: Path) -> str:
    h = xxhash.xxh128()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def process_one_clip(
    src: Path,
    out_dir: Path,
    state: State,
    client: GeminiClient,
    semaphore: asyncio.Semaphore,
    prompts: dict,
) -> dict:
    """Process one clip with true async Pass B parallelism."""
    async with semaphore:
        t_start = time.time()
        try:
            # Step 1 : probe
            duration = probe_duration(src)
            if duration is None:
                return {"status": "failed", "src": str(src), "error": "probe failed"}

            # Step 2 : hash
            clip_hash = hash_file(src)

            # Step 3 : transcode (sync, I/O bound)
            proxy_path = out_dir / f"{clip_hash}_720p.mp4"
            if not proxy_path.exists():
                loop = asyncio.get_event_loop()
                ok = await loop.run_in_executor(
                    None, lambda: transcode_proxy_ffmpeg_nvenc(src, proxy_path)
                )
                if not ok:
                    state.update_clip_status(clip_hash, "transcode_failed")
                    return {"status": "failed", "src": str(src), "error": "transcode"}

            # Step 4 : upload
            file = await client.upload_video_async(proxy_path)

            # Step 5 : Pass A factuel (vidéo, séquentiel car il fournit le contexte)
            pass_a_system = f"{prompts['pass_a']}\n\n---\n\n{prompts['goldberg_context']}"
            pass_a, meta_a = await client.generate_structured_async(
                model=MODEL_PASS_A_FALLBACK,
                contents=[file, "Analyse ce clip et produis le JSON Pass A factuel selon les instructions du system prompt."],
                schema=PassA,
                system_instruction=pass_a_system,
                thinking_level="low",
            )
            pass_a.clip_hash = clip_hash
            pass_a.clip_path = str(src)
            pass_a.technique.duration_s = duration
            pass_a_json = pass_a.model_dump_json(indent=2)

            # Step 6+7+8 : Pass B en asyncio.gather (vrai parallélisme async)
            common_input = (
                "Voici le JSON Pass A factuel d'un clip Goldberg. Produis ton analyse selon ton rôle :\n\n"
                f"```json\n{pass_a_json}\n```"
            )
            murch_system = f"{prompts['murch']}\n\n---\n\nCONTEXTE PROJET :\n{prompts['goldberg_context']}"
            baxter_system = f"{prompts['baxter']}\n\n---\n\nCONTEXTE PROJET :\n{prompts['goldberg_context']}"
            pagh_system = f"{prompts['pagh']}\n\n---\n\nCONTEXTE PROJET :\n{prompts['goldberg_context']}"

            (murch_res, baxter_res, pagh_res) = await asyncio.gather(
                client.generate_structured_async(
                    MODEL_PASS_B_REASONING, [common_input], Murch, murch_system, "low",
                ),
                client.generate_structured_async(
                    MODEL_PASS_B_REASONING, [common_input], Baxter, baxter_system, "low",
                ),
                client.generate_structured_async(
                    MODEL_PASS_B_REASONING, [common_input], PaghAndersen, pagh_system, "low",
                ),
            )
            murch, meta_m = murch_res
            baxter, meta_b = baxter_res
            pagh, meta_p = pagh_res
            murch.clip_hash = clip_hash
            baxter.clip_hash = clip_hash
            pagh.clip_hash = clip_hash

            # Step 9 : Janet Malcolm conditionnel
            malcolm = None
            meta_mal = None
            if pass_a.project_tags.sensitive_flags:
                malcolm_system = f"{prompts['malcolm']}\n\n---\n\nCONTEXTE PROJET :\n{prompts['goldberg_context']}"
                malcolm_input = (
                    f"Ce clip a été flaggé sensible. Produis ton verdict éthique :\n\nPASS A:\n```json\n{pass_a_json}\n```"
                )
                malcolm_res = await client.generate_structured_async(
                    MODEL_PASS_B_REASONING, [malcolm_input], JanetMalcolm, malcolm_system, "low",
                )
                malcolm, meta_mal = malcolm_res
                malcolm.clip_hash = clip_hash

            # Step 10 : Synthèse FCP
            synthese_input = (
                "Tu es le synthétiseur final pour Final Cut Pro 12. Produis une fiche 3 lignes + keywords + priority + intent.\n\n"
                f"PASS A:\n```json\n{pass_a_json}\n```\n\n"
                f"MURCH:\n```json\n{murch.model_dump_json(indent=2)}\n```\n\n"
                f"BAXTER:\n```json\n{baxter.model_dump_json(indent=2)}\n```\n\n"
                f"PAGH:\n```json\n{pagh.model_dump_json(indent=2)}\n```"
            )
            if malcolm:
                synthese_input += f"\n\nMALCOLM:\n```json\n{malcolm.model_dump_json(indent=2)}\n```"

            synthese, meta_s = await client.generate_structured_async(
                MODEL_PASS_B_REASONING, [synthese_input], SyntheseFCP,
                "Tu es le synthétiseur final. Output JSON strict selon SyntheseFCP schema. Phrases courtes.",
                "minimal",
            )
            synthese.clip_hash = clip_hash

            # Cost logging
            all_metas = [meta_a, meta_m, meta_b, meta_p, meta_s]
            if meta_mal:
                all_metas.append(meta_mal)

            for pass_name, meta in zip(
                ["pass_a", "murch", "baxter", "pagh_andersen", "synthese"] + (["janet_malcolm"] if meta_mal else []),
                all_metas,
            ):
                state.log_cost(
                    model=meta["model"], tokens_in=meta["tokens_in"],
                    tokens_out=meta["tokens_out"], cost_usd=meta["cost_usd"],
                    clip_hash=clip_hash, pass_name=pass_name,
                )

            total_cost = sum(m["cost_usd"] for m in all_metas)

            # Build ClipAnalysis + write JSON + FCPXML
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
                timings_s={"total": time.time() - t_start},
            )
            (out_dir / f"{clip_hash}_FINAL.json").write_text(
                analysis.model_dump_json(indent=2), encoding="utf-8"
            )
            try:
                write_fcpxml(analysis, out_dir / f"{clip_hash}.fcpxml")
            except Exception as e:
                print(f"[async] {clip_hash[:12]} fcpxml write warning: {e}")

            state.update_clip_status(clip_hash, "done")
            client.delete_uploaded(file.name)

            duration_real = time.time() - t_start
            verdict = getattr(murch, "statut_prise", "?")
            print(
                f"[async] ✓ {clip_hash[:12]} {src.name} {duration_real:.1f}s ${total_cost:.4f} [{verdict}]",
                flush=True,
            )

            return {
                "status": "ok",
                "hash": clip_hash,
                "cost_usd": total_cost,
                "duration_s": duration_real,
                "verdict": verdict,
            }

        except Exception as e:
            print(f"[async] ✗ {src.name}: {e}", flush=True)
            import traceback; traceback.print_exc()
            try:
                state.update_clip_status(clip_hash, "failed")
            except Exception:
                pass
            return {"status": "failed", "src": str(src), "error": str(e)}


async def run_async_batch(
    db_path: Path,
    out_dir: Path,
    limit: int,
    workers: int,
    budget_cap: float,
    media_type: Optional[str] = "video",
):
    state = State(db_path)
    client = GeminiClient()

    # Preload all prompts
    prompts = {
        "pass_a": load_prompt("pass_a_factuel"),
        "murch": load_prompt("murch_v1"),
        "baxter": load_prompt("baxter_v1"),
        "pagh": load_prompt("pagh_andersen_v1"),
        "malcolm": load_prompt("janet_malcolm_v1"),
        "goldberg_context": load_prompt("goldberg_context_v1"),
    }

    print(f"\n{'='*60}")
    print(f"FILM-INDEXER async batch (true parallelism)")
    print(f"DB         : {db_path}")
    print(f"Workers    : {workers} (asyncio.Semaphore)")
    print(f"Budget cap : ${budget_cap}")
    print(f"Limit      : {limit}")
    print(f"{'='*60}\n")

    pending = state.list_clips(status="pending", media_type=media_type, limit=limit)
    print(f"[async] {len(pending)} pending clips\n")

    if not pending:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(workers)

    t_start = time.time()
    tasks = []
    for row in pending:
        clip_path = Path(row["canonical_path"])
        if not clip_path.exists():
            state.update_clip_status(row["hash"], "missing")
            continue
        # Budget check
        if state.total_cost() >= budget_cap:
            print(f"[async] BUDGET CAP REACHED")
            break

        tasks.append(asyncio.create_task(
            process_one_clip(clip_path, out_dir, state, client, semaphore, prompts)
        ))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    wall_clock = time.time() - t_start

    ok = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ok")
    failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "failed")
    total_cost = sum(r.get("cost_usd", 0) for r in results if isinstance(r, dict))

    print(f"\n{'='*60}")
    print(f"ASYNC BATCH DONE")
    print(f"  Wall clock : {wall_clock:.1f}s")
    print(f"  OK         : {ok}")
    print(f"  FAILED     : {failed}")
    print(f"  Total cost : ${total_cost:.4f}")
    print(f"  Avg/clip   : ${total_cost/max(ok,1):.4f}")
    print(f"  DB stats   : {state.stats()}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("C:/Goldberg/film-indexer/state.db"))
    parser.add_argument("--out", type=Path, default=Path("C:/Goldberg/film-indexer/output"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--budget-cap", type=float, default=30.0)
    parser.add_argument("--media-type", type=str, default="video")
    args = parser.parse_args()

    asyncio.run(run_async_batch(
        db_path=args.db, out_dir=args.out,
        limit=args.limit, workers=args.workers,
        budget_cap=args.budget_cap, media_type=args.media_type,
    ))


if __name__ == "__main__":
    main()
