"""
Phase 0 — Scan inventaire complet de tous les médias.

Walker récursif sur les drives (Nav3, Nav4, iCloud, NAS).
Hash xxh128 parallèle.
Probe metadata via ffprobe / exiftool.
Écrit dans SQLite WAL pour resume safe.

Usage :
    python scan_drives.py --roots F:/ G:/ --since 2026-02-18 \\
                          --db C:/Goldberg/film-indexer/state.db

Filtres :
- Extensions vidéo : .braw .mov .mp4 .mxf .m4v .mkv
- Extensions audio : .wav .mp3 .m4a .aiff .flac
- Extensions images : .jpg .jpeg .heic .dng .raw .tif .tiff .png .cr2 .nef .arw
- Filtre date >= --since (par mtime)

Resume : si un hash existe déjà dans clips, on ajoute juste un nouveau clip_path
(pour les mirrors Nav3/Nav4 qui ont le même fichier sur 2 drives).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import xxhash

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from film_indexer.state.db import State


VIDEO_EXTS = {".braw", ".mov", ".mp4", ".mxf", ".m4v", ".mkv", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aiff", ".aif", ".flac", ".aac", ".ogg"}
IMAGE_EXTS = {".jpg", ".jpeg", ".heic", ".dng", ".tif", ".tiff", ".png", ".cr2", ".nef", ".arw", ".raf"}
ALL_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

# Skip these directories
SKIP_DIRS = {"$RECYCLE.BIN", "System Volume Information", ".fseventsd", ".Spotlight-V100", ".Trashes", "node_modules", ".git"}


def get_media_type(ext: str) -> Optional[str]:
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def hash_file_xxh128(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute xxh128 hash of a file."""
    h = xxhash.xxh128()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def get_drive_label(path: Path) -> Optional[str]:
    """Get drive letter on Windows, mountpoint on Unix."""
    parts = path.parts
    if len(parts) >= 1 and len(parts[0]) >= 2 and parts[0][1] == ":":
        return parts[0][0].upper() + ":"
    return parts[0] if parts else None


def scan_one_root(
    root: Path,
    state: State,
    since: Optional[datetime],
    skip_hash: bool = False,
) -> dict:
    """Scan one root directory and upsert into SQLite."""
    stats = {"files_seen": 0, "files_added": 0, "files_skipped": 0, "errors": 0, "bytes": 0}

    def walk():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                yield Path(dirpath) / fname

    files = []
    for fp in walk():
        ext = fp.suffix.lower()
        if ext not in ALL_EXTS:
            continue
        try:
            stat = fp.stat()
        except (FileNotFoundError, PermissionError, OSError):
            stats["errors"] += 1
            continue
        if since:
            mtime = datetime.fromtimestamp(stat.st_mtime)
            if mtime < since:
                stats["files_skipped"] += 1
                continue
        files.append((fp, stat))

    print(f"[scan] {root}: {len(files)} candidate files", flush=True)

    if skip_hash:
        # Inventory only mode — write entries with no hash
        for fp, stat in files:
            stats["files_seen"] += 1
            stats["bytes"] += stat.st_size
            try:
                fake_hash = f"NOHASH_{fp.name}_{stat.st_size}_{int(stat.st_mtime)}"
                state.upsert_clip(
                    hash=fake_hash,
                    canonical_path=str(fp),
                    drive=get_drive_label(fp),
                    size_bytes=stat.st_size,
                    format=fp.suffix.lower().lstrip("."),
                    media_type=get_media_type(fp.suffix.lower()),
                    mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                )
                stats["files_added"] += 1
            except Exception as e:
                print(f"[scan] error on {fp}: {e}", flush=True)
                stats["errors"] += 1
        return stats

    # Parallel hashing (16 workers)
    def hash_and_upsert(item):
        fp, stat = item
        try:
            h = hash_file_xxh128(fp)
            state.upsert_clip(
                hash=h,
                canonical_path=str(fp),
                drive=get_drive_label(fp),
                size_bytes=stat.st_size,
                format=fp.suffix.lower().lstrip("."),
                media_type=get_media_type(fp.suffix.lower()),
                mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )
            state.add_clip_path(
                hash=h,
                path=str(fp),
                drive=get_drive_label(fp),
                size_bytes=stat.st_size,
                mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            )
            return ("ok", fp, h, stat.st_size)
        except Exception as e:
            return ("error", fp, str(e), 0)

    t_start = time.time()
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(hash_and_upsert, item) for item in files]
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            stats["files_seen"] += 1
            if result[0] == "ok":
                stats["files_added"] += 1
                stats["bytes"] += result[3]
            else:
                stats["errors"] += 1
            if i % 50 == 0:
                elapsed = time.time() - t_start
                rate = i / elapsed if elapsed > 0 else 0
                print(f"[scan] {root}: {i}/{len(files)} ({rate:.1f} files/s)", flush=True)

    return stats


def main():
    parser = argparse.ArgumentParser(description="Phase 0 — Scan media inventory")
    parser.add_argument("--roots", nargs="+", required=True, help="Root directories to scan")
    parser.add_argument("--since", type=str, default="2026-02-18", help="ISO date (mtime filter)")
    parser.add_argument("--db", type=Path, default=Path("C:/Goldberg/film-indexer/state.db"), help="SQLite database path")
    parser.add_argument("--no-hash", action="store_true", help="Inventory only, skip hashing (fast)")
    args = parser.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    state = State(args.db)

    print(f"\n{'='*60}")
    print(f"FILM-INDEXER Phase 0 — Inventaire scan")
    print(f"Roots : {args.roots}")
    print(f"Since : {since}")
    print(f"DB    : {args.db}")
    print(f"Hash  : {'SKIPPED' if args.no_hash else 'xxh128 parallel'}")
    print(f"{'='*60}\n")

    total = {"files_seen": 0, "files_added": 0, "files_skipped": 0, "errors": 0, "bytes": 0}
    for root_str in args.roots:
        root = Path(root_str)
        if not root.exists():
            print(f"[scan] SKIP missing root: {root}")
            continue
        stats = scan_one_root(root, state, since, skip_hash=args.no_hash)
        for k, v in stats.items():
            total[k] = total.get(k, 0) + v

    print(f"\n{'='*60}")
    print(f"DONE — {total['files_added']} files added")
    print(f"  Seen     : {total['files_seen']}")
    print(f"  Skipped  : {total['files_skipped']}")
    print(f"  Errors   : {total['errors']}")
    print(f"  Total GB : {total['bytes'] / 1e9:.1f}")
    print(f"\nDB stats: {state.stats()}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
