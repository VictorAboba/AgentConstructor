"""End-to-end graph runs on the mock model in the local sandbox."""
import asyncio
import copy
from pathlib import Path

import pytest

from app import templates
from app.db import db
from app.engine import runner
from app.engine.validate import validate_graph


def run_graph(data: dict, task: str = "What is 2+3?", expected: str | None = "5", item_meta: dict | None = None) -> dict:
    data = copy.deepcopy(data)
    data.setdefault("settings", {})["sandbox"] = {"type": "local"}
    run_id = runner.create_run_row({"id": None, "name": "test", "data": data}, task, expected)
    asyncio.run(runner.execute_run(run_id, data, task, expected, item_meta))
    run = db.get("runs", run_id)
    run["spans"] = db.query("SELECT * FROM spans WHERE run_id = ? ORDER BY started_at", [run_id])
    return run


def events(run: dict, kind: str) -> list[dict]:
    return [s["data"] for s in run["spans"] if (s["data"] or {}).get("kind") == kind]


@pytest.mark.parametrize("template_id", [t["id"] for t in templates.TEMPLATES])
def test_template_validates_and_runs(mock_model_id, template_id):
    data = templates.build(template_id, mock_model_id)
    check = validate_graph(data, runner.load_models())
    assert check["ok"], check["errors"]
    run = run_graph(data)
    assert run["status"] == "done", run["error"]
    assert run["correct"] == 1, run["answer"]
    assert run["llm_calls"] > 0 and run["input_tokens"] > 0


def test_catalog_has_both_languages():
    for t in templates.catalog():
        assert t["summary"] and t["summary_ru"] and t["measure"] and t["measure_ru"]
        assert t["preview"]["nodes"]


def _board_graph(mock_model_id: str, authors: list[str]) -> dict:
    agent = lambda nid, label, x: {"id": nid, "type": "agent", "position": {"x": x, "y": 0},
                                   "data": {"label": label, "model_id": mock_model_id, "system_prompt": "Solve.", "tools": []}}
    edge = lambda eid, s, t, kind, **d: {"id": eid, "source": s, "target": t, "data": {"kind": kind, **d}}
    return {
        "nodes": [{"id": "in", "type": "input", "position": {"x": 0, "y": 0}, "data": {"label": "Input"}},
                  agent("a", "Alice", 200), agent("b", "Bob", 200),
                  {"id": "board", "type": "board", "position": {"x": 400, "y": 0}, "data": {"label": "Board"}},
                  agent("s", "Sub", 600),
                  {"id": "out", "type": "output", "position": {"x": 800, "y": 0}, "data": {"label": "Output"}}],
        "edges": [edge("e1", "in", "a", "flow"), edge("e2", "in", "b", "flow"),
                  edge("p1", "a", "board", "message"), edge("p2", "b", "board", "message"),
                  edge("sub", "s", "board", "subscribe", authors=authors), edge("o", "s", "out", "flow")],
    }


@pytest.mark.parametrize("authors, delivered", [
    ([], {"Alice", "Bob"}), (["a"], {"Alice"}), (["b"], {"Bob"}), (["a", "b"], {"Alice", "Bob"}), (["gone"], set()),
])
def test_subscription_author_filter(mock_model_id, authors, delivered):
    run = run_graph(_board_graph(mock_model_id, authors))
    assert run["status"] == "done", run["error"]
    assert {e["from"] for e in events(run, "post")} == {"a", "b"}
    assert {e["author"] for e in events(run, "board")} == delivered


def test_subscription_validation(mock_model_id):
    data = _board_graph(mock_model_id, ["a", "zz"])
    check = validate_graph(data, runner.load_models())
    assert any("missing nodes ['zz']" in e for e in check["errors"])


def test_folder_files_are_copied(mock_model_id, tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print(1)\n")
    (tmp_path / "notes.md").write_text("skip me\n")
    data = templates.build("single", mock_model_id)
    run = run_graph(data, item_meta={"files_from": {"dir": str(tmp_path), "glob": ["*.py"]}})
    assert run["status"] == "done", run["error"]
    workspace = Path(run["workspace"])
    assert (workspace / "src" / "main.py").read_text() == "print(1)\n"
    assert not (workspace / "notes.md").exists()
    sandbox = next(s for s in run["spans"] if s["kind"] == "sandbox")
    assert sandbox["data"]["files_from"]["count"] == 1 and len(sandbox["data"]["files_from"]["sha"]) == 16
