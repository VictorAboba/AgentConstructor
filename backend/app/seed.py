"""First-start content (an offline mock model, example architectures, a toy dataset) and data migrations."""
from __future__ import annotations

from .db import db, new_id, now
from .templates import TEMPLATES

EXAMPLES_FLAG = "examples_v2"


def _flag(key: str) -> bool:
    return db.one("SELECT value FROM kv WHERE key = ?", [key]) is not None


def _set_flag(key: str) -> None:
    db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, '1')", [key])


def add_examples(model_id: str) -> None:
    """One graph per template, skipping names that already exist. Runs once per database, so examples
    the user deletes do not come back."""
    if _flag(EXAMPLES_FLAG):
        return
    existing = {g["name"] for g in db.query("SELECT name FROM graphs")}
    for t in reversed(TEMPLATES):  # the editor lists the most recently updated first
        if t["name"] not in existing:
            db.insert("graphs", {"id": new_id("g_"), "name": t["name"], "data": t["build"](model_id),
                                 "created_at": now(), "updated_at": now()})
    _set_flag(EXAMPLES_FLAG)


def migrate() -> None:
    """Brings stored graphs up to date with the current engine."""
    for g in db.query("SELECT id, data FROM graphs"):
        data, changed = g["data"], False
        for n in data.get("nodes", []):
            tools = (n.get("data") or {}).get("tools")
            if isinstance(tools, list) and "finish" in tools:  # removed: a turn now ends with a reply without tools
                n["data"]["tools"] = [t for t in tools if t != "finish"]
                changed = True
        if changed:
            db.update("graphs", g["id"], {"data": data})
    mock = db.one("SELECT id FROM models WHERE provider = 'mock' ORDER BY created_at LIMIT 1")
    if mock:
        add_examples(mock["id"])


def seed() -> None:
    if db.one("SELECT id FROM models LIMIT 1") or db.one("SELECT id FROM graphs LIMIT 1"):
        migrate()
        return
    db.insert("models", {"id": new_id("m_"), "name": "mock", "provider": "mock", "model": "mock-1", "base_url": "",
                         "api_key": "", "price_in": 1.0, "price_out": 5.0, "extra": {}, "created_at": now()})
    ds = new_id("ds_")
    items = [("What is 17 + 25?", "42"), ("Compute 12 * 12.", "144"), ("What is 100 - 58?", "42"),
             ("What is 81 / 9?", "9"), ("Name the capital of France.", "Paris"), ("What is 7 x 6?", "42")]
    db.insert("datasets", {"id": ds, "name": "toy-arithmetic", "description": "Smoke-test dataset",
                           "item_count": len(items), "created_at": now()})
    db.insert_many("dataset_items", [{"id": new_id("it_"), "dataset_id": ds, "idx": i, "task": t, "answer": a, "meta": {}}
                                     for i, (t, a) in enumerate(items)])
    migrate()
