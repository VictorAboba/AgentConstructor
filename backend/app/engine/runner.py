"""Run lifecycle (sandbox → graph → scoring) and dataset experiments."""
from __future__ import annotations

import asyncio
import shutil
import statistics
import time
from collections import defaultdict

from ..datasets import DatasetError, fingerprint, select_files
from ..db import db, new_id, now
from ..providers import LLMParams, ProviderError, get_provider
from ..tools.sandbox import SandboxConfig, SandboxError, make_sandbox
from .evaluator import JUDGE_PROMPT, parse_judge, score_rule
from .graph import GraphError, GraphRun, execute_graph
from .tracer import Tracer

ACTIVE: dict[str, asyncio.Task] = {}


def load_models() -> dict[str, dict]:
    return {m["id"]: m for m in db.query("SELECT * FROM models")}


def create_run_row(graph_row: dict, task: str, expected: str | None, *, experiment_id: str | None = None,
                   item: dict | None = None, idx: int = 0, repeat: int = 0, snapshot: bool = True) -> str:
    run_id = new_id("run_")
    db.insert("runs", {
        "id": run_id, "experiment_id": experiment_id, "graph_id": graph_row.get("id"),
        "graph_name": graph_row.get("name"), "item_id": (item or {}).get("id"), "idx": idx, "repeat": repeat,
        "task": task, "expected": expected, "status": "queued", "created_at": now(),
        "graph_snapshot": graph_row["data"] if snapshot else None,
    })
    return run_id


async def _judge(tracer: Tracer, scorer: dict, task: str, expected: str, answer: str) -> tuple[bool | None, str]:
    models = load_models()
    cfg = models.get(scorer.get("judge_model_id") or "")
    if not cfg:
        return None, "judge model not configured"
    provider = get_provider(cfg)
    prompt = JUDGE_PROMPT.format(task=task, expected=expected, answer=answer)
    span = tracer.start("judge", cfg["name"], data={"prompt": prompt, "model": cfg["model"]})
    try:
        r = await provider.complete("", [{"role": "user", "content": prompt}], [], LLMParams(max_tokens=4000))
    except ProviderError as e:
        tracer.end(span, "error", {"error": str(e)})
        return None, f"judge error: {e}"
    span.input_tokens, span.output_tokens, span.cost = r.input_tokens, r.output_tokens, provider.cost(r)
    verdict = parse_judge(r.text)
    tracer.end(span, "ok", {"text": r.text, "verdict": verdict})
    return verdict, r.text.strip().splitlines()[-1][:300] if r.text.strip() else ""


async def execute_run(run_id: str, graph: dict, task: str, expected: str | None,
                      item_meta: dict | None = None, scorer: dict | None = None) -> None:
    scorer = scorer or {"type": "auto"}
    item_meta = item_meta or {}
    started = time.time()
    db.update("runs", run_id, {"status": "running", "started_at": started})
    tracer = Tracer(run_id)
    root = tracer.start("run", graph.get("name") or "run", data={"task": task, "expected": expected})
    tracer.root_id = root.id

    settings = graph.get("settings") or {}
    sb_cfg = SandboxConfig.from_dict(settings.get("sandbox"))
    sandbox = make_sandbox(run_id, sb_cfg)
    db.update("runs", run_id, {"workspace": str(sandbox.root)})

    status, answer, error, cancelled = "done", None, None, False
    run: GraphRun | None = None
    try:
        async with tracer.span("sandbox", f"{sandbox.kind} sandbox", data={"config": sb_cfg.__dict__}) as s:
            await sandbox.start()
            if item_meta.get("files_from"):
                spec = item_meta["files_from"]
                try:  # off the event loop: a folder can be large
                    picked = await asyncio.to_thread(select_files, spec)
                except DatasetError as e:
                    raise SandboxError(f"dataset files: {e}")
                await asyncio.to_thread(sandbox.copy_in, picked)
                s.data["files_from"] = {**spec, "count": len(picked), "bytes": sum(f.stat().st_size for _, f in picked),
                                        "sha": await asyncio.to_thread(fingerprint, picked),
                                        "files": [rel for rel, _ in picked[:200]]}
            sandbox.seed(item_meta.get("files") or {})
            setup = item_meta.get("setup") or settings.get("setup_command")
            if setup:
                r = await sandbox.exec(setup, timeout=600)
                s.data["setup"] = {"command": setup, "exit_code": r.exit_code, "stdout": r.stdout[-4000:], "stderr": r.stderr[-4000:]}
        run = GraphRun(graph, task, tracer, sandbox, load_models())
        answer = await execute_graph(run)
        if run.errors:
            error = "; ".join(run.errors)
        if answer is None:
            status = "error"
            error = error or "graph produced no output"
    except asyncio.CancelledError:
        status, cancelled = "cancelled", True
    except (GraphError, SandboxError, ProviderError) as e:
        status, error = "error", str(e)
    except Exception as e:  # noqa: BLE001 — a run must always be finalized
        status, error = "error", f"{type(e).__name__}: {e}"
    finally:
        try:
            await asyncio.shield(sandbox.stop())
        except Exception:  # noqa: BLE001
            pass

    correct, judge_note = None, None
    if status == "done" and not cancelled:
        if scorer.get("type") == "llm_judge" and expected:
            correct, judge_note = await _judge(tracer, scorer, task, expected, answer or "")
        else:
            correct, judge_note = score_rule(scorer, expected, answer)

    tracer.end(root, {"done": "ok", "error": "error", "cancelled": "cancelled"}[status],
               {"answer": answer, "error": error, "correct": correct})
    ended = time.time()
    db.update("runs", run_id, {
        "status": status, "answer": answer, "error": error, "ended_at": ended,
        "duration_ms": (ended - started) * 1000, "correct": None if correct is None else int(correct),
        "score": None if correct is None else float(correct), "judge_note": judge_note,
        **tracer.totals, "node_stats": dict(tracer.node_stats),
    })
    if not settings.get("keep_workspace", True):
        shutil.rmtree(sandbox.root, ignore_errors=True)
    if cancelled:
        raise asyncio.CancelledError


def start_run(run_id: str, graph: dict, task: str, expected: str | None, scorer: dict | None = None) -> None:
    async def wrapper():
        try:
            await execute_run(run_id, graph, task, expected, None, scorer)
        except asyncio.CancelledError:
            pass
        finally:
            ACTIVE.pop(run_id, None)
    ACTIVE[run_id] = asyncio.create_task(wrapper())


# ---- experiments -------------------------------------------------------------------------

def launch_experiment(graph_row: dict, dataset_row: dict, cfg: dict, name: str = "") -> str:
    """Creates the experiment and its queued runs (one per item × repeat) and starts it."""
    items = db.query("SELECT * FROM dataset_items WHERE dataset_id = ? ORDER BY idx", [dataset_row["id"]])
    if cfg.get("limit"):
        items = items[: int(cfg["limit"])]
    if not items:
        raise ValueError("dataset is empty")
    exp_id = new_id("exp_")
    db.insert("experiments", {
        "id": exp_id, "name": name or f"{graph_row['name']} × {dataset_row['name']}", "graph_id": graph_row["id"],
        "graph_name": graph_row["name"], "graph_snapshot": graph_row["data"] | {"name": graph_row["name"]},
        "dataset_id": dataset_row["id"], "dataset_name": dataset_row["name"], "config": cfg,
        "status": "queued", "created_at": now(), "summary": {},
    })
    for it in items:
        for rep in range(max(1, int(cfg.get("repeats") or 1))):
            create_run_row(graph_row, it["task"], it["answer"], experiment_id=exp_id, item=it, idx=it["idx"],
                           repeat=rep, snapshot=False)
    start_experiment(exp_id)
    return exp_id


def start_experiment(exp_id: str) -> None:
    async def wrapper():
        try:
            await execute_experiment(exp_id)
        except asyncio.CancelledError:
            db.execute("UPDATE runs SET status='cancelled' WHERE experiment_id=? AND status IN ('queued','running')", [exp_id])
            db.update("experiments", exp_id, {"status": "cancelled", "ended_at": now(), "summary": summarize(exp_id)})
        finally:
            ACTIVE.pop(exp_id, None)
    ACTIVE[exp_id] = asyncio.create_task(wrapper())


async def execute_experiment(exp_id: str) -> None:
    exp = db.get("experiments", exp_id)
    cfg = exp["config"] or {}
    graph = exp["graph_snapshot"]
    db.update("experiments", exp_id, {"status": "running", "started_at": now()})
    runs = db.query("SELECT r.id, r.task, r.expected, i.meta FROM runs r LEFT JOIN dataset_items i ON i.id = r.item_id "
                    "WHERE r.experiment_id = ? ORDER BY r.idx, r.repeat", [exp_id])
    sem = asyncio.Semaphore(max(1, int(cfg.get("concurrency") or 4)))

    async def one(r: dict):
        async with sem:
            await execute_run(r["id"], graph, r["task"], r["expected"], r.get("meta") or {}, cfg.get("scorer"))

    await asyncio.gather(*(one(r) for r in runs))
    db.update("experiments", exp_id, {"status": "done", "ended_at": now(), "summary": summarize(exp_id)})


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def summarize(exp_id: str) -> dict:
    runs = db.query("SELECT status, correct, duration_ms, input_tokens, output_tokens, cached_tokens, cost, llm_calls, "
                    "tool_calls, activations, node_stats FROM runs WHERE experiment_id = ?", [exp_id])
    finished = [r for r in runs if r["status"] in ("done", "error")]
    scored = [r for r in finished if r["correct"] is not None]
    durations = [r["duration_ms"] for r in finished if r["duration_ms"]]
    judge = db.one("SELECT COALESCE(SUM(s.cost),0) AS cost, COALESCE(SUM(s.input_tokens + s.output_tokens),0) AS tokens "
                   "FROM spans s JOIN runs r ON r.id = s.run_id WHERE r.experiment_id = ? AND s.kind = 'judge'", [exp_id])
    nodes: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for r in finished:
        for nid, st in (r["node_stats"] or {}).items():
            for k, v in st.items():
                nodes[nid][k] += v or 0
    n = len(finished) or 1

    def mean(key):
        return sum(r[key] or 0 for r in finished) / n if finished else None

    return {
        "total": len(runs),
        "finished": len(finished),
        "running": sum(r["status"] == "running" for r in runs),
        "queued": sum(r["status"] == "queued" for r in runs),
        "errors": sum(r["status"] == "error" for r in runs),
        "scored": len(scored),
        "correct": sum(r["correct"] for r in scored),
        "accuracy": (sum(r["correct"] for r in scored) / len(scored)) if scored else None,
        "duration_mean_ms": statistics.mean(durations) if durations else None,
        "duration_median_ms": statistics.median(durations) if durations else None,
        "duration_p95_ms": _pct(durations, 0.95),
        "input_tokens": sum(r["input_tokens"] or 0 for r in finished),
        "output_tokens": sum(r["output_tokens"] or 0 for r in finished),
        "cached_tokens": sum(r["cached_tokens"] or 0 for r in finished),
        "tokens_mean": (sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0) for r in finished) / n) if finished else None,
        "cost": sum(r["cost"] or 0 for r in finished),
        "cost_mean": mean("cost"),
        "llm_calls_mean": mean("llm_calls"),
        "tool_calls_mean": mean("tool_calls"),
        "activations_mean": mean("activations"),
        "judge_cost": judge["cost"] if judge else 0,
        "judge_tokens": judge["tokens"] if judge else 0,
        "nodes": {k: dict(v) for k, v in nodes.items()},
    }


def cancel(task_id: str) -> bool:
    t = ACTIVE.get(task_id)
    if t and not t.done():
        t.cancel()
        return True
    return False


def recover_interrupted() -> None:
    """Runs left 'running' by a previous server process can never finish."""
    db.execute("UPDATE runs SET status='error', error='server restarted during run' WHERE status IN ('queued','running')")
    db.execute("UPDATE experiments SET status='error' WHERE status IN ('queued','running')")
    db.execute("UPDATE spans SET status='error' WHERE status='running'")
