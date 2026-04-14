"""
SQLite WAL state store pour film-indexer.

Tables :
- clips           : 1 ligne par fichier physique (hash, path, size, format, status)
- runs            : 1 ligne par run du pipeline (run_id, prompts versions, model)
- artifacts       : 1 ligne par (clip_hash, pass_name) — JSON output validé
- costs           : 1 ligne par appel Gemini (timestamp, model, tokens, usd)

Mode WAL pour reads/writes concurrents. Idempotency via composite keys.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS clips (
    hash             TEXT PRIMARY KEY,
    canonical_path   TEXT NOT NULL,
    drive            TEXT,
    size_bytes       INTEGER,
    duration_s       REAL,
    format           TEXT,
    media_type       TEXT,            -- video | audio | image
    mtime_iso        TEXT,
    capture_date     TEXT,            -- parsed from path or exif
    status           TEXT NOT NULL DEFAULT 'pending',
    tier             TEXT,            -- light | standard | deep
    schema_version   TEXT NOT NULL DEFAULT '1.0.0',
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_drive ON clips(drive);
CREATE INDEX IF NOT EXISTS idx_clips_media_type ON clips(media_type);
CREATE INDEX IF NOT EXISTS idx_clips_capture_date ON clips(capture_date);

CREATE TABLE IF NOT EXISTS clip_paths (
    -- Une ligne par "présence physique" d'un même hash sur un drive
    hash             TEXT NOT NULL,
    path             TEXT NOT NULL,
    drive            TEXT,
    size_bytes       INTEGER,
    mtime_iso        TEXT,
    PRIMARY KEY (hash, path),
    FOREIGN KEY (hash) REFERENCES clips(hash)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at         TEXT,
    prompts_versions TEXT,    -- JSON: {murch:"v1", baxter:"v1", pagh:"v1"}
    model_ids        TEXT,    -- JSON: {pass_a:"...", pass_b:"..."}
    status           TEXT NOT NULL DEFAULT 'running',
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
    hash             TEXT NOT NULL,
    pass_name        TEXT NOT NULL,    -- pass_a | murch | baxter | pagh_andersen | janet_malcolm | synthese
    schema_version   TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    model_id         TEXT NOT NULL,
    blob             TEXT NOT NULL,    -- JSON output
    cost_usd         REAL DEFAULT 0,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    latency_s        REAL DEFAULT 0,
    run_id           TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (hash, pass_name, prompt_version, model_id),
    FOREIGN KEY (hash) REFERENCES clips(hash)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);

CREATE TABLE IF NOT EXISTS costs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL DEFAULT (datetime('now')),
    run_id           TEXT,
    clip_hash        TEXT,
    pass_name        TEXT,
    model            TEXT NOT NULL,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    cost_usd         REAL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_costs_run ON costs(run_id);
CREATE INDEX IF NOT EXISTS idx_costs_timestamp ON costs(timestamp);
"""


class State:
    """SQLite state store."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ============================================================
    # CLIPS
    # ============================================================

    def upsert_clip(
        self,
        hash: str,
        canonical_path: str,
        drive: Optional[str] = None,
        size_bytes: Optional[int] = None,
        duration_s: Optional[float] = None,
        format: Optional[str] = None,
        media_type: Optional[str] = None,
        mtime_iso: Optional[str] = None,
        capture_date: Optional[str] = None,
    ):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO clips (hash, canonical_path, drive, size_bytes, duration_s, format, media_type, mtime_iso, capture_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET
                    canonical_path=excluded.canonical_path,
                    size_bytes=COALESCE(excluded.size_bytes, clips.size_bytes),
                    duration_s=COALESCE(excluded.duration_s, clips.duration_s),
                    format=COALESCE(excluded.format, clips.format),
                    media_type=COALESCE(excluded.media_type, clips.media_type),
                    mtime_iso=COALESCE(excluded.mtime_iso, clips.mtime_iso),
                    capture_date=COALESCE(excluded.capture_date, clips.capture_date),
                    updated_at=datetime('now')
            """, (hash, canonical_path, drive, size_bytes, duration_s, format, media_type, mtime_iso, capture_date))

    def add_clip_path(self, hash: str, path: str, drive: Optional[str], size_bytes: Optional[int], mtime_iso: Optional[str]):
        with self.connect() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO clip_paths (hash, path, drive, size_bytes, mtime_iso)
                VALUES (?, ?, ?, ?, ?)
            """, (hash, path, drive, size_bytes, mtime_iso))

    def get_clip(self, hash: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM clips WHERE hash = ?", (hash,)).fetchone()
            return dict(row) if row else None

    def list_clips(self, status: Optional[str] = None, media_type: Optional[str] = None, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            sql = "SELECT * FROM clips WHERE 1=1"
            params = []
            if status:
                sql += " AND status = ?"
                params.append(status)
            if media_type:
                sql += " AND media_type = ?"
                params.append(media_type)
            sql += " ORDER BY capture_date DESC, hash LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def update_clip_status(self, hash: str, status: str):
        with self.connect() as conn:
            conn.execute("UPDATE clips SET status = ?, updated_at = datetime('now') WHERE hash = ?", (status, hash))

    # ============================================================
    # ARTIFACTS
    # ============================================================

    def save_artifact(
        self,
        hash: str,
        pass_name: str,
        blob: Any,
        schema_version: str,
        prompt_version: str,
        model_id: str,
        cost_usd: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_s: float = 0.0,
        run_id: Optional[str] = None,
    ):
        if not isinstance(blob, str):
            blob = json.dumps(blob, ensure_ascii=False)
        with self.connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO artifacts (
                    hash, pass_name, schema_version, prompt_version, model_id,
                    blob, cost_usd, tokens_in, tokens_out, latency_s, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hash, pass_name, schema_version, prompt_version, model_id, blob, cost_usd, tokens_in, tokens_out, latency_s, run_id))

    def has_artifact(self, hash: str, pass_name: str, prompt_version: str, model_id: str) -> bool:
        """Idempotency check: skip if already done."""
        with self.connect() as conn:
            row = conn.execute("""
                SELECT 1 FROM artifacts
                WHERE hash = ? AND pass_name = ? AND prompt_version = ? AND model_id = ?
                LIMIT 1
            """, (hash, pass_name, prompt_version, model_id)).fetchone()
            return row is not None

    def get_artifact(self, hash: str, pass_name: str) -> Optional[dict]:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT * FROM artifacts WHERE hash = ? AND pass_name = ?
                ORDER BY created_at DESC LIMIT 1
            """, (hash, pass_name)).fetchone()
            return dict(row) if row else None

    # ============================================================
    # RUNS
    # ============================================================

    def create_run(self, run_id: str, prompts_versions: dict, model_ids: dict, notes: str = ""):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO runs (run_id, prompts_versions, model_ids, notes)
                VALUES (?, ?, ?, ?)
            """, (run_id, json.dumps(prompts_versions), json.dumps(model_ids), notes))

    def end_run(self, run_id: str, status: str = "completed"):
        with self.connect() as conn:
            conn.execute("""
                UPDATE runs SET ended_at = datetime('now'), status = ? WHERE run_id = ?
            """, (status, run_id))

    # ============================================================
    # COSTS
    # ============================================================

    def log_cost(self, model: str, tokens_in: int, tokens_out: int, cost_usd: float, **kwargs):
        with self.connect() as conn:
            conn.execute("""
                INSERT INTO costs (model, tokens_in, tokens_out, cost_usd, run_id, clip_hash, pass_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (model, tokens_in, tokens_out, cost_usd, kwargs.get("run_id"), kwargs.get("clip_hash"), kwargs.get("pass_name")))

    def total_cost(self, run_id: Optional[str] = None) -> float:
        with self.connect() as conn:
            sql = "SELECT COALESCE(SUM(cost_usd), 0) as total FROM costs"
            params = []
            if run_id:
                sql += " WHERE run_id = ?"
                params.append(run_id)
            row = conn.execute(sql, params).fetchone()
            return row["total"]

    def stats(self) -> dict:
        with self.connect() as conn:
            return {
                "clips_total": conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0],
                "clips_pending": conn.execute("SELECT COUNT(*) FROM clips WHERE status='pending'").fetchone()[0],
                "clips_done": conn.execute("SELECT COUNT(*) FROM clips WHERE status='done'").fetchone()[0],
                "artifacts_total": conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
                "total_cost_usd": conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM costs").fetchone()[0],
            }
