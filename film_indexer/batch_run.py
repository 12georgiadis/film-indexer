"""
Phase 3 — Orchestrateur batch async pour film-indexer.

Lit la SQLite state.db, sélectionne les clips status='pending' ou 'transcoded',
et lance le pipeline complet sur chaque clip avec :
- asyncio.Semaphore(N_WORKERS) pour limiter la concurrence Gemini
- Idempotency via has_artifact() check
- Cost tracker + budget hard cap
- Resume safe via SQLite

Usage :
    python batch_run.py --db state.db --limit 10 --workers 4 --budget-cap 30

Pour le PoC, on délègue à poc_single_clip.run_pipeline pour chaque clip.
Plus tard, on intégrera directement dans une boucle async pure.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from film_indexer.state.db import State
from film_indexer.poc_single_clip import run_pipeline


async def process_clip(
    clip_hash: str,
    clip_path: Path,
    out_dir: Path,
    state: State,
    state_db_path: Path,
    semaphore: asyncio.Semaphore,
    executor: ThreadPoolExecutor,
) -> dict:
    """Process one clip end-to-end via the PoC pipeline (run in thread executor)."""
    async with semaphore:
        loop = asyncio.get_event_loop()
        try:
            print(f"[batch] start {clip_hash[:12]} {clip_path.name}")
            # Pass state_db_path so run_pipeline logs costs
            analysis = await loop.run_in_executor(
                executor,
                lambda: run_pipeline(clip_path, out_dir, state_db_path),
            )
            state.update_clip_status(clip_hash, "done")
            return {
                "hash": clip_hash,
                "status": "ok",
                "cost_usd": analysis.total_cost_usd,
                "duration": sum(analysis.timings_s.values()),
            }
        except Exception as e:
            print(f"[batch] FAIL {clip_hash[:12]}: {e}")
            traceback.print_exc()
            state.update_clip_status(clip_hash, "failed")
            return {"hash": clip_hash, "status": "failed", "error": str(e)}


async def run_batch(
    db_path: Path,
    out_dir: Path,
    limit: int,
    workers: int,
    budget_cap: float,
    media_type: Optional[str] = "video",
):
    state = State(db_path)

    print(f"\n{'='*60}")
    print(f"FILM-INDEXER Batch Phase 3")
    print(f"DB         : {db_path}")
    print(f"Out dir    : {out_dir}")
    print(f"Workers    : {workers}")
    print(f"Budget cap : ${budget_cap}")
    print(f"Limit      : {limit}")
    print(f"Media type : {media_type}")
    print(f"{'='*60}\n")

    pending = state.list_clips(status="pending", media_type=media_type, limit=limit)
    print(f"[batch] {len(pending)} clips to process\n")

    if not pending:
        print("[batch] nothing to do")
        return

    semaphore = asyncio.Semaphore(workers)
    executor = ThreadPoolExecutor(max_workers=workers)

    tasks = []
    for row in pending:
        clip_path = Path(row["canonical_path"])
        if not clip_path.exists():
            print(f"[batch] SKIP missing file: {clip_path}")
            state.update_clip_status(row["hash"], "missing")
            continue

        # Budget check
        current_cost = state.total_cost()
        if current_cost >= budget_cap:
            print(f"[batch] BUDGET CAP REACHED ${current_cost:.2f} >= ${budget_cap}")
            break

        task = asyncio.create_task(
            process_clip(
                row["hash"],
                clip_path,
                out_dir,
                state,
                db_path,
                semaphore,
                executor,
            )
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Stats
    ok = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "ok")
    failed = sum(1 for r in results if isinstance(r, dict) and r.get("status") == "failed")
    total_cost = sum(r.get("cost_usd", 0) for r in results if isinstance(r, dict))

    print(f"\n{'='*60}")
    print(f"BATCH DONE")
    print(f"  OK     : {ok}")
    print(f"  FAILED : {failed}")
    print(f"  Cost   : ${total_cost:.4f}")
    print(f"  DB stats: {state.stats()}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Batch orchestrator")
    parser.add_argument("--db", type=Path, default=Path("C:/Goldberg/film-indexer/state.db"))
    parser.add_argument("--out", type=Path, default=Path("C:/Goldberg/film-indexer/output"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4, help="Concurrent Gemini calls")
    parser.add_argument("--budget-cap", type=float, default=30.0, help="USD hard cap")
    parser.add_argument("--media-type", type=str, default="video", help="video|audio|image")
    args = parser.parse_args()

    asyncio.run(run_batch(
        db_path=args.db,
        out_dir=args.out,
        limit=args.limit,
        workers=args.workers,
        budget_cap=args.budget_cap,
        media_type=args.media_type,
    ))


if __name__ == "__main__":
    main()
