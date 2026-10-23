"""MCP server (streamable HTTP at /mcp) so coding agents such as Claude Code can set up models,
build graphs, prepare datasets, launch runs and experiments and read results."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .datasets import DatasetError, normalize_item, parse_dataset
from .db import db, new_id, now
from .engine import runner
from .engine.evaluator import SCORERS
from .engine.validate import validate_graph
from .providers import PROVIDERS, LLMParams, ProviderError, get_provider
from . import templates
from .tools.builtin import BUILTIN_TOOLS

UI = "http://localhost:8000"

GUIDE = """AgentConstructor builds multi-agent systems as graphs and measures them (accuracy, latency, tokens, cost, traces).

Graph JSON: {"nodes": [...], "edges": [...], "settings": {...}}
Node: {"id": str, "type": "input"|"agent"|"vote"|"board"|"output", "position": {"x": num, "y": num}, "data": {...}}
  input  — emits the task. output — the last message it receives is the answer that gets scored.
  vote   — majority vote over incoming answers (extracts <answer>…</answer>).
  board  — message board; data: {"label"}.
  agent  — data: {"label", "model_id", "system_prompt", "tools": [names], "max_steps": 15, "max_tokens": 16000,
           "effort": null|"low"|"medium"|"high"|"xhigh"|"max", "temperature": null, "memory": "persistent"|"fresh",
           "join": "all"|"any", "include_task": true, "auto_context": true}
           A turn ends when the model replies without calling tools; that reply is the agent's output.
Edge: {"id": str, "source": node id, "target": node id, "data": {"kind": ..., ...}}
  flow                       — pass the output on (into a board: post it)
  conditional {condition}    — pass if condition matches: {"type": "contains"|"not_contains"|"regex", "value": str}
  feedback {condition, max_iterations} — back-edge for loops
  handoff {label}            — source gets handoff_to_<target>; transfers control and ends its turn
  delegate {label}           — source gets ask_<target>; target runs as a sub-agent, answer returned as tool result
  message {bidirectional, label} — source gets message_<target> (agent) or post_<board> (board) without ending its turn;
                               bidirectional gives the reverse direction too
  subscribe {authors}        — agent ↔ board: the agent receives the board's posts; authors = list of node ids
                               to receive only their posts (empty/missing = every post)
Settings: {"sandbox": {"type": "docker"|"local", "image": "python:3.12-slim", "network": false, "timeout": 60},
           "max_activations": 40, "timeout_s": 900, "keep_workspace": true, "setup_command": ""}
Dataset item: {"task": str, "answer": str, "files": {path: content}?, "setup": shell command?, ...extra meta}
Scorers: """ + ", ".join(f"{k} ({v})" for k, v in SCORERS.items())

mcp = MCPServer("AgentConstructor", instructions=GUIDE)


def _need(table: str, id_: str) -> dict:
    row = db.get(table, id_)
    if row is None:
        raise ValueError(f"{table[:-1]} {id_!r} not found")
    return row


def _models() -> dict[str, dict]:
    return {m["id"]: m for m in db.query("SELECT * FROM models")}


def _run_summary(r: dict) -> dict:
    keys = ("id", "status", "task", "expected", "answer", "correct", "error", "duration_ms", "input_tokens",
            "output_tokens", "cached_tokens", "cost", "llm_calls", "tool_calls", "activations")
    return {k: r.get(k) for k in keys} | {"url": f"{UI}/#/runs/{r['id']}"}


# ---- overview ----------------------------------------------------------------------------

@mcp.tool()
def overview() -> dict:
    """Start here: the graph/dataset schema, available providers, tools and scorers, and what exists now."""
    return {
        "guide": GUIDE,
        "providers": {k: v["label"] for k, v in PROVIDERS.items()},
        "agent_tools": {n: t.spec.description for n, t in BUILTIN_TOOLS.items()},
        "counts": {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("models", "graphs", "datasets", "experiments", "runs")},
        "ui": UI,
    }


# ---- models ------------------------------------------------------------------------------

@mcp.tool()
def list_models() -> list[dict]:
    """Configured model connections (API keys are never returned)."""
    return [{k: m[k] for k in ("id", "name", "provider", "model", "base_url", "price_in", "price_out")} | {"has_key": bool(m["api_key"])}
            for m in db.query("SELECT * FROM models ORDER BY created_at")]


@mcp.tool()
def add_model(name: str, provider: str, model: str, base_url: str = "", api_key: str = "",
              price_in: float = 0, price_out: float = 0, extra: dict | None = None) -> dict:
    """Add a model connection. provider: openai|anthropic|openrouter|vllm|ollama|mock. Prices are $ per 1M tokens.
    Leave api_key empty to use the provider's environment variable (e.g. ANTHROPIC_API_KEY)."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; expected one of {list(PROVIDERS)}")
    mid = new_id("m_")
    db.insert("models", {"id": mid, "name": name, "provider": provider, "model": model, "base_url": base_url,
                         "api_key": api_key, "price_in": price_in, "price_out": price_out, "extra": extra or {},
                         "created_at": now()})
    return {"id": mid}


@mcp.tool()
async def test_model(model_id: str) -> dict:
    """Send a one-word prompt to check credentials and latency."""
    cfg = _need("models", model_id)
    t0 = time.time()
    try:
        r = await get_provider(cfg).complete("", [{"role": "user", "content": "Reply with the single word: OK"}], [],
                                             LLMParams(max_tokens=2000))
    except ProviderError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "text": r.text[:100], "latency_ms": round((time.time() - t0) * 1000), "served_by": r.model}


# ---- graphs ------------------------------------------------------------------------------

@mcp.tool()
def list_graphs() -> list[dict]:
    """Saved graphs (id, name, size)."""
    out = []
    for g in db.query("SELECT id, name, data, updated_at FROM graphs ORDER BY updated_at DESC"):
        out.append({"id": g["id"], "name": g["name"], "nodes": len(g["data"].get("nodes", [])),
                    "edges": len(g["data"].get("edges", [])), "url": f"{UI}/#/graphs/{g['id']}"})
    return out


@mcp.tool()
def get_graph(graph_id: str) -> dict:
    """Full graph JSON (nodes, edges, settings) plus validation results."""
    g = _need("graphs", graph_id)
    return {"id": g["id"], "name": g["name"], "data": g["data"], "validation": validate_graph(g["data"], _models())}


@mcp.tool()
def save_graph(name: str, nodes: list[dict], edges: list[dict], settings: dict | None = None,
               graph_id: str | None = None) -> dict:
    """Create (no graph_id) or replace a graph. See `overview` for the node/edge schema. Nodes without a
    position are laid out automatically. Returns validation errors/warnings; invalid graphs are not saved."""
    for i, n in enumerate(nodes):
        n.setdefault("position", {"x": 260 * (i % 5), "y": 160 * (i // 5)})
        n.setdefault("data", {}).setdefault("label", n.get("id"))
    for i, e in enumerate(edges):
        e.setdefault("id", f"e{i}_{e.get('source')}_{e.get('target')}")
        e.setdefault("data", {}).setdefault("kind", "flow")
    data: dict[str, Any] = {"nodes": nodes, "edges": edges}
    if graph_id:
        data["settings"] = settings if settings is not None else (_need("graphs", graph_id)["data"].get("settings") or {})
    else:
        data["settings"] = settings or {"sandbox": {"type": "docker", "image": "python:3.12-slim", "network": False, "timeout": 60},
                                        "max_activations": 40, "timeout_s": 900, "keep_workspace": True}
    check = validate_graph(data, _models())
    if not check["ok"]:
        return {"saved": False, **check}
    if graph_id:
        _need("graphs", graph_id)
        db.update("graphs", graph_id, {"name": name, "data": data, "updated_at": now()})
    else:
        graph_id = new_id("g_")
        db.insert("graphs", {"id": graph_id, "name": name, "data": data, "created_at": now(), "updated_at": now()})
    return {"saved": True, "id": graph_id, "url": f"{UI}/#/graphs/{graph_id}", **check}


@mcp.tool()
def list_templates() -> list[dict]:
    """Starter architectures (single agent baseline, pipeline, reflection, ensembles, orchestrator, hierarchy,
    router, debate, swarm, blackboard…) with what each is good for and what to measure."""
    return [{k: t[k] for k in ("id", "name", "category", "summary", "measure", "agents")} for t in templates.catalog()]


@mcp.tool()
def create_graph_from_template(template_id: str, model_id: str, name: str = "") -> dict:
    """Create a graph from a starter architecture with every agent on the given model. Edit it afterwards
    with get_graph / save_graph (e.g. different models per agent, prompts, tools)."""
    if template_id not in templates.BY_ID:
        raise ValueError(f"unknown template {template_id!r}; see list_templates")
    _need("models", model_id)
    gid = new_id("g_")
    db.insert("graphs", {"id": gid, "name": name or templates.BY_ID[template_id]["name"],
                         "data": templates.build(template_id, model_id), "created_at": now(), "updated_at": now()})
    return {"id": gid, "url": f"{UI}/#/graphs/{gid}"}


@mcp.tool()
def delete_graph(graph_id: str) -> dict:
    """Delete a graph (its past runs and experiments stay)."""
    db.delete("graphs", graph_id)
    return {"ok": True}


# ---- datasets ----------------------------------------------------------------------------

@mcp.tool()
def list_datasets() -> list[dict]:
    """Datasets with item counts."""
    return db.query("SELECT id, name, description, item_count, created_at FROM datasets ORDER BY created_at DESC")


@mcp.tool()
def get_dataset(dataset_id: str, offset: int = 0, limit: int = 20) -> dict:
    """A page of dataset items."""
    ds = _need("datasets", dataset_id)
    ds["items"] = db.query("SELECT idx, task, answer, meta FROM dataset_items WHERE dataset_id = ? ORDER BY idx LIMIT ? OFFSET ?",
                           [dataset_id, limit, offset])
    return ds


def _insert_items(dataset_id: str, items: list[dict], start: int) -> int:
    rows = [{"id": new_id("it_"), "dataset_id": dataset_id, "idx": start + i, **normalize_item(it)} for i, it in enumerate(items)]
    db.insert_many("dataset_items", rows)
    count = db.one("SELECT COUNT(*) AS n FROM dataset_items WHERE dataset_id = ?", [dataset_id])["n"]
    db.update("datasets", dataset_id, {"item_count": count})
    return count


@mcp.tool()
def create_dataset(name: str, items: list[dict], description: str = "") -> dict:
    """Create a dataset from items like {"task": ..., "answer": ..., "files": {...}?, "setup": "..."?}.
    Field aliases are accepted (question/prompt/input, expected/target/solution)."""
    try:
        [normalize_item(it) for it in items]
    except DatasetError as e:
        raise ValueError(str(e))
    did = new_id("ds_")
    db.insert("datasets", {"id": did, "name": name, "description": description, "item_count": 0, "created_at": now()})
    return {"id": did, "item_count": _insert_items(did, items, 0), "url": f"{UI}/#/datasets/{did}"}


@mcp.tool()
def add_dataset_items(dataset_id: str, items: list[dict]) -> dict:
    """Append items to an existing dataset."""
    _need("datasets", dataset_id)
    last = db.one("SELECT COALESCE(MAX(idx), -1) AS m FROM dataset_items WHERE dataset_id = ?", [dataset_id])["m"]
    try:
        return {"item_count": _insert_items(dataset_id, items, last + 1)}
    except DatasetError as e:
        raise ValueError(str(e))


@mcp.tool()
def import_dataset_file(path: str, name: str = "", description: str = "") -> dict:
    """Import a local JSONL / JSON / CSV / TSV file (absolute path on this machine) as a dataset."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"file not found: {p}")
    try:
        items = parse_dataset(p.name, p.read_bytes())
    except DatasetError as e:
        raise ValueError(str(e))
    did = new_id("ds_")
    db.insert("datasets", {"id": did, "name": name or p.stem, "description": description, "item_count": len(items), "created_at": now()})
    db.insert_many("dataset_items", [{"id": new_id("it_"), "dataset_id": did, "idx": i, **it} for i, it in enumerate(items)])
    return {"id": did, "item_count": len(items), "url": f"{UI}/#/datasets/{did}"}


@mcp.tool()
def delete_dataset(dataset_id: str) -> dict:
    """Delete a dataset and its items."""
    db.execute("DELETE FROM dataset_items WHERE dataset_id = ?", [dataset_id])
    db.delete("datasets", dataset_id)
    return {"ok": True}


# ---- runs --------------------------------------------------------------------------------

async def _wait(table: str, id_: str, timeout_s: float) -> dict:
    deadline = time.time() + timeout_s
    while True:
        row = db.get(table, id_)
        if row["status"] not in ("queued", "running") or time.time() > deadline:
            return row
        await asyncio.sleep(1.0)


@mcp.tool()
async def run_task(graph_id: str, task: str, expected: str | None = None, wait: bool = True, timeout_s: int = 600) -> dict:
    """Run a graph on one task. With wait=true returns the answer, score, time, tokens and cost
    (use get_run for the trace); otherwise returns the run id immediately."""
    g = _need("graphs", graph_id)
    check = validate_graph(g["data"], _models())
    if not check["ok"]:
        return {"started": False, **check}
    run_id = runner.create_run_row(g, task, expected)
    runner.start_run(run_id, g["data"] | {"name": g["name"]}, task, expected, {"type": "auto"})
    if not wait:
        return {"id": run_id, "url": f"{UI}/#/runs/{run_id}"}
    return _run_summary(await _wait("runs", run_id, timeout_s))


@mcp.tool()
def get_run(run_id: str, full: bool = False) -> dict:
    """Run result and its trace as a timeline (agent activations, model calls, tool calls, messages, thoughts).
    full=true includes system prompts and untruncated texts."""
    r = _need("runs", run_id)
    clip = (lambda s: s) if full else (lambda s: s if s is None or len(s) <= 400 else s[:400] + "…")
    timeline = []
    spans = db.query("SELECT * FROM spans WHERE run_id = ? ORDER BY started_at", [run_id])
    t0 = spans[0]["started_at"] if spans else 0
    for s in spans:
        d = s["data"] or {}
        item: dict[str, Any] = {"t_ms": round((s["started_at"] - t0) * 1000), "kind": s["kind"], "name": s["name"],
                                "node": s["node_id"], "status": s["status"]}
        if s["duration_ms"]:
            item["duration_ms"] = round(s["duration_ms"])
        if s["input_tokens"] or s["output_tokens"]:
            item["tokens"] = [s["input_tokens"], s["output_tokens"]]
        if s["kind"] == "node":
            item |= {"input": clip(d.get("input")), "output": clip(d.get("output")), "steps": d.get("steps")}
            if full:
                item["system"] = d.get("system")
        elif s["kind"] == "llm":
            item |= {"text": clip(d.get("text")), "tool_calls": [c["name"] for c in d.get("tool_calls") or []]}
        elif s["kind"] == "tool":
            item |= {"arguments": d.get("arguments") if full else clip(str(d.get("arguments"))), "result": clip(d.get("result"))}
        elif s["kind"] in ("message", "thought"):
            item |= {"text": clip(d.get("content") or d.get("text")), "edge_kind": d.get("kind") or d.get("source")}
        elif d.get("error"):
            item["error"] = d["error"]
        timeline.append(item)
    return _run_summary(r) | {"node_stats": r.get("node_stats"), "timeline": timeline}


# ---- experiments -------------------------------------------------------------------------

@mcp.tool()
async def start_experiment(graph_id: str, dataset_id: str, scorer: str = "auto", judge_model_id: str | None = None,
                     concurrency: int = 4, repeats: int = 1, limit: int | None = None, name: str = "") -> dict:
    """Evaluate a graph on a dataset. scorer: auto|exact|contains|numeric|regex|llm_judge|none
    (llm_judge needs judge_model_id). repeats runs every item several times to measure variance."""
    g = _need("graphs", graph_id)
    ds = _need("datasets", dataset_id)
    check = validate_graph(g["data"], _models())
    if not check["ok"]:
        return {"started": False, **check}
    if scorer not in SCORERS:
        raise ValueError(f"unknown scorer {scorer!r}")
    cfg = {"scorer": {"type": scorer, "judge_model_id": judge_model_id}, "concurrency": concurrency,
           "repeats": repeats, "limit": limit}
    exp_id = runner.launch_experiment(g, ds, cfg, name)
    return {"id": exp_id, "url": f"{UI}/#/experiments/{exp_id}"}


def _summary(eid: str) -> dict:
    e = _need("experiments", eid)
    s = runner.summarize(eid) if e["status"] in ("queued", "running") or not e.get("summary") else e["summary"]
    return {"id": eid, "name": e["name"], "status": e["status"], "graph": e["graph_name"], "dataset": e["dataset_name"],
            "summary": s, "url": f"{UI}/#/experiments/{eid}"}


@mcp.tool()
async def get_experiment(experiment_id: str, wait: bool = False, timeout_s: int = 1800, include_runs: bool = False) -> dict:
    """Experiment metrics (accuracy, latency mean/median/p95, tokens and cost per task, per-agent breakdown).
    wait=true blocks until it finishes; include_runs adds per-item results."""
    if wait:
        await _wait("experiments", experiment_id, timeout_s)
    out = _summary(experiment_id)
    if include_runs:
        out["runs"] = [_run_summary(r) for r in db.query("SELECT * FROM runs WHERE experiment_id = ? ORDER BY idx, repeat", [experiment_id])]
    return out


@mcp.tool()
def list_experiments(limit: int = 20) -> list[dict]:
    """Recent experiments with headline metrics."""
    out = []
    for e in db.query("SELECT id FROM experiments ORDER BY created_at DESC LIMIT ?", [limit]):
        s = _summary(e["id"])
        m = s["summary"] or {}
        out.append({k: s[k] for k in ("id", "name", "status", "graph", "dataset")} | {
            "accuracy": m.get("accuracy"), "duration_mean_ms": m.get("duration_mean_ms"),
            "tokens_mean": m.get("tokens_mean"), "cost": m.get("cost"), "finished": m.get("finished"), "total": m.get("total")})
    return out


@mcp.tool()
def compare_experiments(experiment_ids: list[str]) -> dict:
    """Side-by-side metrics and per-item correctness of several experiments (ideally on the same dataset)."""
    metrics = ("accuracy", "duration_mean_ms", "duration_p95_ms", "tokens_mean", "cost_mean", "llm_calls_mean",
               "tool_calls_mean", "errors")
    table, items = {}, {}
    for eid in experiment_ids:
        s = _summary(eid)
        table[s["name"]] = {k: (s["summary"] or {}).get(k) for k in metrics}
        for r in db.query("SELECT idx, repeat, correct, status FROM runs WHERE experiment_id = ? ORDER BY idx, repeat", [eid]):
            items.setdefault(r["idx"], {}).setdefault(s["name"], []).append("error" if r["status"] == "error" else r["correct"])
    return {"metrics": table, "per_item": items, "url": f"{UI}/#/compare?ids={','.join(experiment_ids)}"}


@mcp.tool()
async def cancel(run_or_experiment_id: str) -> dict:
    """Stop a running run or experiment."""
    return {"cancelled": runner.cancel(run_or_experiment_id)}
