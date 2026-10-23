"""Span-based tracing persisted to SQLite.

Span kinds: run, sandbox, node (one agent activation), llm, tool, judge; instant events: message
(edge delivery, direct message, board post), thought (model reasoning / think tool), inject
(messages delivered into a running agent), vote, limit. Spans are written at start (status=running) so the UI can show live progress.
"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from ..db import db, new_id

MAX_STR = 20000


def clip(value: Any, limit: int = MAX_STR) -> Any:
    if isinstance(value, str):
        if len(value) > limit:
            return value[: limit // 2] + f"\n…[{len(value) - limit} chars truncated]…\n" + value[-limit // 2:]
        return value
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


@dataclass
class Span:
    id: str
    kind: str
    name: str
    parent_id: str | None
    node_id: str | None
    started_at: float
    data: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


def _empty_stats() -> dict:
    return {"activations": 0, "llm_calls": 0, "tool_calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cached_tokens": 0, "cost": 0.0, "duration_ms": 0.0, "errors": 0}


class Tracer:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.root_id: str | None = None
        self.totals = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost": 0.0,
                       "llm_calls": 0, "tool_calls": 0, "activations": 0}
        self.node_stats: dict[str, dict] = defaultdict(_empty_stats)

    # ---- spans -------------------------------------------------------------------------
    def start(self, kind: str, name: str, parent_id: str | None = None, node_id: str | None = None,
              data: dict | None = None) -> Span:
        span = Span(new_id("sp_"), kind, name, parent_id if parent_id is not None else self.root_id, node_id,
                    time.time(), dict(data or {}))
        db.insert("spans", {
            "id": span.id, "run_id": self.run_id, "parent_id": span.parent_id, "kind": kind, "name": name,
            "node_id": node_id, "started_at": span.started_at, "status": "running", "data": clip(span.data),
        })
        return span

    def end(self, span: Span, status: str = "ok", data: dict | None = None) -> float:
        ended = time.time()
        if data:
            span.data.update(data)
        duration = (ended - span.started_at) * 1000
        db.update("spans", span.id, {
            "ended_at": ended, "duration_ms": duration, "status": status, "data": clip(span.data),
            "input_tokens": span.input_tokens, "output_tokens": span.output_tokens, "cost": span.cost,
        })
        return duration

    def event(self, kind: str, name: str, parent_id: str | None = None, node_id: str | None = None,
              data: dict | None = None, status: str = "ok", at: float | None = None) -> None:
        t = at if at is not None else time.time()
        db.insert("spans", {
            "id": new_id("sp_"), "run_id": self.run_id, "parent_id": parent_id if parent_id is not None else self.root_id,
            "kind": kind, "name": name, "node_id": node_id, "started_at": t, "ended_at": t, "duration_ms": 0,
            "status": status, "data": clip(data or {}),
        })

    @asynccontextmanager
    async def span(self, kind: str, name: str, parent_id: str | None = None, node_id: str | None = None,
                   data: dict | None = None):
        s = self.start(kind, name, parent_id, node_id, data)
        try:
            yield s
        except BaseException as e:
            self.end(s, "error", {"error": f"{type(e).__name__}: {e}"})
            raise
        else:
            self.end(s, s.data.pop("_status", "ok"))

    # ---- accounting --------------------------------------------------------------------
    def record_llm(self, node_id: str | None, input_tokens: int, output_tokens: int, cached: int, cost: float,
                   count: bool = True) -> None:
        if not count:
            return
        for bucket in (self.totals, self.node_stats[node_id or "_"]):
            bucket["input_tokens"] += input_tokens
            bucket["output_tokens"] += output_tokens
            bucket["cached_tokens"] += cached
            bucket["cost"] += cost
            bucket["llm_calls"] += 1
        self.flush()

    def record_tool(self, node_id: str | None) -> None:
        self.totals["tool_calls"] += 1
        self.node_stats[node_id or "_"]["tool_calls"] += 1

    def record_activation(self, node_id: str, duration_ms: float, error: bool = False) -> None:
        self.totals["activations"] += 1
        st = self.node_stats[node_id]
        st["activations"] += 1
        st["duration_ms"] += duration_ms
        st["errors"] += int(error)
        self.flush()

    def flush(self) -> None:
        db.update("runs", self.run_id, {**self.totals, "node_stats": dict(self.node_stats)})
