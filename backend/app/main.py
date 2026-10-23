from __future__ import annotations

import asyncio
import csv
import io
import json
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .datasets import DatasetError, parse_dataset
from .db import db, new_id, now
from .engine import runner
from .engine.evaluator import SCORERS
from .engine.validate import EDGE_KINDS, validate_graph
from .mcp_server import mcp
from .providers import PROVIDERS, LLMParams, ProviderError, get_provider
from .seed import seed
from . import templates
from .tools.builtin import BUILTIN_TOOLS, DEFAULT_AGENT_TOOLS
from .tools.sandbox import docker_status

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
def _warm_provider_sdks() -> None:
    # The first SDK import/client in a fresh process can take many seconds on Windows; doing it here
    # keeps that one-off cost out of the first measured run's latency.
    from .providers import anthropic_provider, openai_provider  # noqa: F401


async def lifespan(_: FastAPI):
    runner.recover_interrupted()
    seed()
    threading.Thread(target=_warm_provider_sdks, daemon=True).start()
    async with mcp.session_manager.run():
        yield
    for task in list(runner.ACTIVE.values()):
        task.cancel()


app = FastAPI(title="AgentConstructor", lifespan=lifespan)
# MCP over streamable HTTP at /mcp (e.g. `claude mcp add --transport http agentconstructor http://localhost:8000/mcp`).
# Its route is added directly so it sits ahead of the SPA catch-all and keeps the exact /mcp path.
app.router.routes.extend(mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True).routes)


def _404(what: str):
    raise HTTPException(404, f"{what} not found")


# ---- meta ------------------------------------------------------------------------------

@app.get("/api/meta")
async def meta():
    docker_ok, docker_detail = await docker_status()
    return {
        "providers": PROVIDERS,
        "tools": [{"name": n, "description": t.spec.description, "category": t.category} for n, t in BUILTIN_TOOLS.items()],
        "default_tools": DEFAULT_AGENT_TOOLS,
        "edge_kinds": sorted(EDGE_KINDS),
        "scorers": SCORERS,
        "docker": docker_ok, "docker_detail": docker_detail,
    }


# ---- models ----------------------------------------------------------------------------

class ModelIn(BaseModel):
    name: str
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    price_in: float = 0
    price_out: float = 0
    extra: dict = Field(default_factory=dict)


def _mask(m: dict) -> dict:
    key = m.get("api_key") or ""
    return {**m, "api_key": (key[:4] + "…" + key[-4:]) if len(key) > 12 else ("•" * len(key) if key else "")}


@app.get("/api/models")
def list_models():
    return [_mask(m) for m in db.query("SELECT * FROM models ORDER BY created_at")]


@app.post("/api/models")
def create_model(body: ModelIn):
    if body.provider not in PROVIDERS:
        raise HTTPException(400, f"unknown provider {body.provider}")
    mid = new_id("m_")
    db.insert("models", {"id": mid, **body.model_dump(), "created_at": now()})
    return _mask(db.get("models", mid))


@app.put("/api/models/{mid}")
def update_model(mid: str, body: ModelIn):
    cur = db.get("models", mid) or _404("model")
    values = body.model_dump()
    if values["api_key"] == _mask(cur)["api_key"]:
        values["api_key"] = cur["api_key"]  # masked value echoed back: keep the stored key
    db.update("models", mid, values)
    return _mask(db.get("models", mid))


@app.delete("/api/models/{mid}")
def delete_model(mid: str):
    db.delete("models", mid)
    return {"ok": True}


@app.post("/api/models/{mid}/test")
async def test_model(mid: str):
    cfg = db.get("models", mid) or _404("model")
    t0 = time.time()
    try:
        r = await get_provider(cfg).complete("", [{"role": "user", "content": "Reply with the single word: OK"}], [],
                                             LLMParams(max_tokens=2000))
    except ProviderError as e:
        return {"ok": False, "error": str(e), "latency_ms": (time.time() - t0) * 1000}
    return {"ok": True, "text": r.text[:200], "latency_ms": (time.time() - t0) * 1000,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "served_by": r.model}


# ---- graphs ----------------------------------------------------------------------------

class GraphIn(BaseModel):
    name: str
    data: dict


@app.get("/api/graphs")
def list_graphs():
    return db.query("SELECT id, name, created_at, updated_at FROM graphs ORDER BY updated_at DESC")


@app.get("/api/graphs/{gid}")
def get_graph(gid: str):
    return db.get("graphs", gid) or _404("graph")


@app.post("/api/graphs")
def create_graph(body: GraphIn):
    gid = new_id("g_")
    db.insert("graphs", {"id": gid, "name": body.name, "data": body.data, "created_at": now(), "updated_at": now()})
    return db.get("graphs", gid)


@app.put("/api/graphs/{gid}")
def update_graph(gid: str, body: GraphIn):
    db.get("graphs", gid) or _404("graph")
    db.update("graphs", gid, {"name": body.name, "data": body.data, "updated_at": now()})
    return db.get("graphs", gid)


class FromTemplateIn(BaseModel):
    template_id: str
    model_id: str
    name: str = ""


@app.get("/api/templates")
def list_templates():
    return templates.catalog()


@app.post("/api/graphs/from-template")
def create_from_template(body: FromTemplateIn):
    if body.template_id not in templates.BY_ID:
        _404("template")
    db.get("models", body.model_id) or _404("model")
    gid = new_id("g_")
    name = body.name or templates.BY_ID[body.template_id]["name"]
    db.insert("graphs", {"id": gid, "name": name, "data": templates.build(body.template_id, body.model_id),
                         "created_at": now(), "updated_at": now()})
    return db.get("graphs", gid)


@app.post("/api/graphs/validate")
def validate(body: GraphIn):
    return validate_graph(body.data, {m["id"]: m for m in db.query("SELECT * FROM models")})


@app.delete("/api/graphs/{gid}")
def delete_graph(gid: str):
    db.delete("graphs", gid)
    return {"ok": True}


# ---- datasets --------------------------------------------------------------------------

@app.get("/api/datasets")
def list_datasets():
    return db.query("SELECT * FROM datasets ORDER BY created_at DESC")


@app.get("/api/datasets/{did}")
def get_dataset(did: str):
    ds = db.get("datasets", did) or _404("dataset")
    ds["items"] = db.query("SELECT * FROM dataset_items WHERE dataset_id = ? ORDER BY idx", [did])
    return ds


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile = File(...), name: str = Form(""), description: str = Form(""),
                         files_dir: str = Form(""), files_glob: str = Form("")):
    """files_dir / files_glob: a folder (and filter) seeded for every item that has no files of its own."""
    defaults = {"files": files_dir, "files_glob": files_glob} if files_dir.strip() else None
    try:
        raw = await file.read()
        items = await asyncio.to_thread(parse_dataset, file.filename or "data.jsonl", raw, None, defaults)
    except DatasetError as e:
        raise HTTPException(400, str(e))
    did = new_id("ds_")
    db.insert("datasets", {"id": did, "name": name or Path(file.filename or "dataset").stem, "description": description,
                           "item_count": len(items), "created_at": now()})
    db.insert_many("dataset_items", [{"id": new_id("it_"), "dataset_id": did, "idx": i, **it} for i, it in enumerate(items)])
    return db.get("datasets", did)


@app.delete("/api/datasets/{did}")
def delete_dataset(did: str):
    db.execute("DELETE FROM dataset_items WHERE dataset_id = ?", [did])
    db.delete("datasets", did)
    return {"ok": True}


# ---- runs ------------------------------------------------------------------------------

class RunIn(BaseModel):
    graph_id: str
    task: str
    expected: str | None = None
    scorer: dict = Field(default_factory=lambda: {"type": "auto"})


@app.post("/api/runs")
async def create_run(body: RunIn):
    g = db.get("graphs", body.graph_id) or _404("graph")
    run_id = runner.create_run_row(g, body.task, body.expected)
    runner.start_run(run_id, g["data"] | {"name": g["name"]}, body.task, body.expected, body.scorer)
    return {"id": run_id}


RUN_LIST_COLS = ("id, experiment_id, graph_id, graph_name, idx, repeat, task, expected, answer, status, correct, "
                 "started_at, ended_at, duration_ms, input_tokens, output_tokens, cached_tokens, cost, llm_calls, "
                 "tool_calls, activations, error, created_at")


@app.get("/api/runs")
def list_runs(graph_id: str | None = None, adhoc: bool = False, limit: int = 200):
    where, params = [], []
    if graph_id:
        where.append("graph_id = ?")
        params.append(graph_id)
    if adhoc:
        where.append("experiment_id IS NULL")
    sql = f"SELECT {RUN_LIST_COLS} FROM runs" + (" WHERE " + " AND ".join(where) if where else "")
    return db.query(sql + " ORDER BY created_at DESC LIMIT ?", [*params, limit])


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    run = db.get("runs", rid) or _404("run")
    if run.get("experiment_id") and not run.get("graph_snapshot"):
        exp = db.get("experiments", run["experiment_id"])
        run["graph_snapshot"] = exp and exp["graph_snapshot"]
    run["spans"] = db.query("SELECT * FROM spans WHERE run_id = ? ORDER BY started_at", [rid])
    return run


@app.post("/api/runs/{rid}/cancel")
async def cancel_run(rid: str):
    return {"ok": runner.cancel(rid)}


@app.delete("/api/runs/{rid}")
async def delete_run(rid: str):
    runner.cancel(rid)
    db.execute("DELETE FROM spans WHERE run_id = ?", [rid])
    db.delete("runs", rid)
    return {"ok": True}


@app.get("/api/runs/{rid}/export")
def export_run(rid: str):
    data = get_run(rid)
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{rid}.json"'})


def _workspace(rid: str) -> Path:
    run = db.get("runs", rid) or _404("run")
    if not run.get("workspace"):
        _404("workspace")
    return Path(run["workspace"])


@app.get("/api/runs/{rid}/files")
def run_files(rid: str):
    root = _workspace(rid)
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and not any(part in (".sandbox", ".git", "node_modules", "__pycache__") for part in rel.parts):
            out.append({"path": rel.as_posix(), "size": p.stat().st_size})
        if len(out) >= 1000:
            break
    return out


@app.get("/api/runs/{rid}/file")
def run_file(rid: str, path: str):
    root = _workspace(rid).resolve()
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file():
        _404("file")
    data = p.read_bytes()[:500_000]
    return {"path": path, "content": data.decode("utf-8", errors="replace"), "size": p.stat().st_size}


# ---- experiments -----------------------------------------------------------------------

class ExperimentIn(BaseModel):
    graph_id: str
    dataset_id: str
    name: str = ""
    scorer: dict = Field(default_factory=lambda: {"type": "auto"})
    concurrency: int = 4
    limit: int | None = None
    repeats: int = 1


@app.post("/api/experiments")
async def create_experiment(body: ExperimentIn):
    g = db.get("graphs", body.graph_id) or _404("graph")
    ds = db.get("datasets", body.dataset_id) or _404("dataset")
    try:
        exp_id = runner.launch_experiment(g, ds, body.model_dump(exclude={"graph_id", "dataset_id", "name"}), body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": exp_id}


@app.get("/api/experiments")
def list_experiments():
    exps = db.query("SELECT id, name, graph_id, graph_name, dataset_id, dataset_name, config, status, created_at, "
                    "started_at, ended_at, summary FROM experiments ORDER BY created_at DESC")
    for e in exps:
        if e["status"] in ("queued", "running"):
            e["summary"] = runner.summarize(e["id"])
    return exps


@app.get("/api/experiments/{eid}")
def get_experiment(eid: str):
    e = db.get("experiments", eid) or _404("experiment")
    if e["status"] in ("queued", "running") or not e.get("summary"):
        e["summary"] = runner.summarize(eid)
    e["runs"] = db.query(f"SELECT {RUN_LIST_COLS}, judge_note FROM runs WHERE experiment_id = ? ORDER BY idx, repeat", [eid])
    return e


@app.post("/api/experiments/{eid}/cancel")
async def cancel_experiment(eid: str):
    return {"ok": runner.cancel(eid)}


@app.delete("/api/experiments/{eid}")
async def delete_experiment(eid: str):
    runner.cancel(eid)
    db.execute("DELETE FROM spans WHERE run_id IN (SELECT id FROM runs WHERE experiment_id = ?)", [eid])
    db.execute("DELETE FROM runs WHERE experiment_id = ?", [eid])
    db.delete("experiments", eid)
    return {"ok": True}


@app.get("/api/experiments/{eid}/export")
def export_experiment(eid: str, format: str = "csv"):
    e = get_experiment(eid)
    cols = ["idx", "repeat", "status", "correct", "task", "expected", "answer", "duration_ms", "input_tokens",
            "output_tokens", "cached_tokens", "cost", "llm_calls", "tool_calls", "activations", "error", "id"]
    if format == "jsonl":
        body = "\n".join(json.dumps({c: r.get(c) for c in cols}, ensure_ascii=False) for r in e["runs"])
        return Response(body, media_type="application/x-ndjson",
                        headers={"Content-Disposition": f'attachment; filename="{eid}.jsonl"'})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    w.writerows(e["runs"])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{eid}.csv"'})


# ---- frontend --------------------------------------------------------------------------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Any:
        if path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        f = FRONTEND_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
