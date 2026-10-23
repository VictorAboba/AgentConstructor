"""SQLite storage. Single connection guarded by a lock: writes are small and frequent
(spans), reads are cheap, so a threadpool/async driver is not worth the complexity."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "agentconstructor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL,
    base_url TEXT, api_key TEXT, price_in REAL DEFAULT 0, price_out REAL DEFAULT 0,
    extra TEXT DEFAULT '{}', created_at REAL
);
CREATE TABLE IF NOT EXISTS graphs (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL, created_at REAL, updated_at REAL
);
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT DEFAULT '', item_count INTEGER DEFAULT 0,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS dataset_items (
    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, idx INTEGER, task TEXT, answer TEXT, meta TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_items_ds ON dataset_items(dataset_id, idx);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY, name TEXT, graph_id TEXT, graph_name TEXT, graph_snapshot TEXT,
    dataset_id TEXT, dataset_name TEXT, config TEXT, status TEXT, created_at REAL,
    started_at REAL, ended_at REAL, summary TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, experiment_id TEXT, graph_id TEXT, graph_name TEXT, item_id TEXT,
    idx INTEGER, repeat INTEGER DEFAULT 0, task TEXT, expected TEXT, answer TEXT, status TEXT,
    correct INTEGER, score REAL, judge_note TEXT, started_at REAL, ended_at REAL, duration_ms REAL,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cached_tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0, llm_calls INTEGER DEFAULT 0, tool_calls INTEGER DEFAULT 0,
    activations INTEGER DEFAULT 0, error TEXT, graph_snapshot TEXT, node_stats TEXT DEFAULT '{}',
    workspace TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS ix_runs_exp ON runs(experiment_id, idx);
CREATE TABLE IF NOT EXISTS spans (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, parent_id TEXT, kind TEXT, name TEXT, node_id TEXT,
    started_at REAL, ended_at REAL, duration_ms REAL, status TEXT,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0,
    data TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_spans_run ON spans(run_id, started_at);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""

JSON_FIELDS = {"extra", "data", "meta", "config", "summary", "graph_snapshot", "node_stats"}


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


class DB:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        out = dict(row)
        for k in JSON_FIELDS & out.keys():
            if isinstance(out[k], str):
                try:
                    out[k] = json.loads(out[k])
                except json.JSONDecodeError:
                    pass
        return out

    @staticmethod
    def _encode(values: dict) -> dict:
        return {
            k: (json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS and not isinstance(v, str) and v is not None else v)
            for k, v in values.items()
        }

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self.lock:
            return [self._decode(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        with self.lock:
            return self._decode(self.conn.execute(sql, tuple(params)).fetchone())

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.lock:
            self.conn.execute(sql, tuple(params))

    def insert(self, table: str, values: dict) -> None:
        values = self._encode(values)
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        self.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values.values())

    def insert_many(self, table: str, rows: list[dict]) -> None:
        if not rows:
            return
        rows = [self._encode(r) for r in rows]
        cols = list(rows[0])
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    def update(self, table: str, id_: str, values: dict) -> None:
        if not values:
            return
        values = self._encode(values)
        sets = ", ".join(f"{k} = ?" for k in values)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*values.values(), id_])

    def get(self, table: str, id_: str) -> dict | None:
        return self.one(f"SELECT * FROM {table} WHERE id = ?", [id_])

    def delete(self, table: str, id_: str) -> None:
        self.execute(f"DELETE FROM {table} WHERE id = ?", [id_])


db = DB()
