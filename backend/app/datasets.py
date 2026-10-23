"""Dataset parsing: JSONL, JSON array/object, CSV/TSV.

Accepted field names (first match wins):
  task:   task, question, input, prompt, problem, query
  answer: answer, expected, output, target, solution, reference, label
Optional: files ({path: content} seeded into the sandbox), setup (shell command run before the
graph); any other fields are kept in meta.
"""
from __future__ import annotations

import csv
import io
import json

TASK_KEYS = ("task", "question", "input", "prompt", "problem", "query")
ANSWER_KEYS = ("answer", "expected", "output", "target", "solution", "reference", "label")


class DatasetError(Exception):
    pass


def _pick(row: dict, keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    lower = {k.lower(): k for k in row}
    for k in keys:
        if k in lower:
            return lower[k], row[lower[k]]
    return None, None


def normalize_item(row: dict) -> dict:
    if not isinstance(row, dict):
        raise DatasetError(f"item is not an object: {str(row)[:80]}")
    tk, task = _pick(row, TASK_KEYS)
    if task is None:
        raise DatasetError(f"item has no task field ({', '.join(TASK_KEYS)}): {json.dumps(row)[:120]}")
    ak, answer = _pick(row, ANSWER_KEYS)
    meta = {k: v for k, v in row.items() if k not in (tk, ak)}
    if isinstance(meta.get("files"), str):
        try:
            meta["files"] = json.loads(meta["files"])
        except json.JSONDecodeError:
            raise DatasetError("'files' must be an object {path: content}")
    as_text = lambda v: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return {"task": as_text(task), "answer": None if answer is None else as_text(answer), "meta": meta}


def parse_dataset(filename: str, raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig", errors="replace").strip()
    if not text:
        raise DatasetError("file is empty")
    name = filename.lower()
    rows: list
    if name.endswith((".csv", ".tsv")):
        dialect = "excel-tab" if name.endswith(".tsv") else "excel"
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    elif name.endswith(".jsonl") or (not text.startswith("[") and "\n" in text and not text.startswith("{\n")):
        rows = []
        for i, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise DatasetError(f"line {i}: {e}")
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise DatasetError(f"invalid JSON: {e}")
        if isinstance(data, dict):
            data = data.get("items") or data.get("data") or data.get("tasks") or [data]
        rows = data
    if not rows:
        raise DatasetError("no items found")
    return [normalize_item(r) for r in rows]
