"""Dataset parsing: JSONL, JSON array/object, CSV/TSV.

Accepted field names (first match wins):
  task:   task, question, input, prompt, problem, query
  answer: answer, expected, output, target, solution, reference, label
Optional: files, setup (shell command run before the graph); any other fields are kept in meta.

files — what is put into the run's sandbox before the graph starts:
  {"calc.py": "..."}                               inline {path: content}
  "C:/bench/repo1"                                 a host folder, copied whole
  {"dir": "C:/bench/repo1", "glob": "**/*.py"}     a folder filtered by patterns
  files_glob                                       the same filter as a separate field (handy in CSV)
Patterns (one string, ";"-separated, or a list): a glob without "/" matches file names at any depth,
one with "/" matches the path from the folder root ("**" = any number of directories), "re:<regex>"
searches the relative path, and a leading "!" excludes. Relative folders resolve against the
dataset file's folder (MCP import) or the project root. A folder may use {field} placeholders
filled from the item, e.g. "tasks/{id}". Folders are copied when each run starts.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath

from .db import DATA_DIR

TASK_KEYS = ("task", "question", "input", "prompt", "problem", "query")
ANSWER_KEYS = ("answer", "expected", "output", "target", "solution", "reference", "label")
PROJECT_ROOT = DATA_DIR.parent
MAX_FILES = 5000
MAX_BYTES = 200 * 1024 * 1024
FILES_FORMS = "'files' must be {path: content}, a folder path or {\"dir\": ..., \"glob\": ...}"


class DatasetError(Exception):
    pass


def _pick(row: dict, keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    lower = {k.lower(): k for k in row}
    for k in keys:
        if k in lower:
            return lower[k], row[lower[k]]
    return None, None


# ---- folder files ---------------------------------------------------------------------------
def _patterns(value) -> list[str]:
    if not value:
        return []
    items = value if isinstance(value, list) else str(value).split(";")
    return [p.strip() for p in items if isinstance(p, str) and p.strip()]


def _glob_regex(pattern: str) -> re.Pattern:
    """Glob → regex: "*" and "?" stay within one path segment, "**" spans directories."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i + 2:]:
            end = pattern.index("]", i + 2)
            body = pattern[i + 1:end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def _matches(rel: PurePosixPath, pattern: str) -> bool:
    if pattern.startswith("re:"):
        return re.search(pattern[3:], rel.as_posix()) is not None
    if "/" not in pattern:
        return _glob_regex(pattern).match(rel.name) is not None
    return _glob_regex(pattern.lstrip("/")).match(rel.as_posix()) is not None


def select_files(spec: dict) -> list[tuple[str, Path]]:
    """Files of a folder spec {dir, glob} as (relative posix path, absolute path), sorted."""
    root = Path(spec["dir"])
    if not root.is_dir():
        raise DatasetError(f"folder not found: {root}")
    pats = _patterns(spec.get("glob"))
    include = [p for p in pats if not p.startswith("!")]
    exclude = [p[1:] for p in pats if p.startswith("!")]
    out, total = [], 0
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel = PurePosixPath(f.relative_to(root).as_posix())
        if include and not any(_matches(rel, p) for p in include):
            continue
        if any(_matches(rel, p) for p in exclude):
            continue
        out.append((rel.as_posix(), f))
        total += f.stat().st_size
        if len(out) > MAX_FILES or total > MAX_BYTES:
            raise DatasetError(f"{root}: more than {MAX_FILES} files or {MAX_BYTES // 2**20} MB selected; narrow it with a glob")
    return out


def fingerprint(files: list[tuple[str, Path]]) -> str:
    """Content hash of the selected files, recorded in the trace so runs on a changed folder stand out."""
    h = hashlib.sha256()
    for rel, f in files:
        h.update(rel.encode() + b"\0" + hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()[:16]


def _folder_spec(value, glob, row: dict, base_dir: Path) -> dict:
    if isinstance(value, dict):
        value, glob = value.get("dir"), value.get("glob", glob)
    if not isinstance(value, str) or not value.strip():
        raise DatasetError("'files' folder must be a path string")
    try:
        value = value.strip().format_map({k: v for k, v in row.items() if isinstance(v, (str, int, float))})
    except (KeyError, ValueError, IndexError) as e:
        raise DatasetError(f"'files' folder {value!r}: unknown placeholder {e}")
    path = Path(value).expanduser()
    path = (path if path.is_absolute() else base_dir / path).resolve()
    spec = {"dir": str(path), "glob": _patterns(glob)}
    for p in spec["glob"]:
        if p.lstrip("!").startswith("re:"):
            try:
                re.compile(p.lstrip("!")[3:])
            except re.error as e:
                raise DatasetError(f"bad regex {p!r}: {e}")
    if not select_files(spec):
        raise DatasetError(f"{path}: no files match {spec['glob'] or 'the folder'}")
    return spec


# ---- items ----------------------------------------------------------------------------------
def normalize_item(row: dict, base_dir: Path | None = None, defaults: dict | None = None) -> dict:
    """`defaults` ({"files": folder, "files_glob": ...}) apply to items that have no files of their own."""
    if not isinstance(row, dict):
        raise DatasetError(f"item is not an object: {str(row)[:80]}")
    tk, task = _pick(row, TASK_KEYS)
    if task is None:
        raise DatasetError(f"item has no task field ({', '.join(TASK_KEYS)}): {json.dumps(row)[:120]}")
    ak, answer = _pick(row, ANSWER_KEYS)
    meta = {k: v for k, v in row.items() if k not in (tk, ak)}
    files, glob = meta.pop("files", None), meta.pop("files_glob", None)
    if files in (None, "") and defaults and defaults.get("files"):
        files, glob = defaults["files"], glob or defaults.get("files_glob")
    if isinstance(files, str) and files.strip().startswith("{"):
        try:
            files = json.loads(files)
        except json.JSONDecodeError:
            raise DatasetError(FILES_FORMS)
    base_dir = base_dir or PROJECT_ROOT
    if isinstance(files, str) and files.strip():
        meta["files_from"] = _folder_spec(files, glob, row, base_dir)
    elif isinstance(files, dict) and "dir" in files and set(files) <= {"dir", "glob"}:
        meta["files_from"] = _folder_spec(files, glob, row, base_dir)
    elif isinstance(files, dict) and files:
        if not all(isinstance(v, str) for v in files.values()):
            raise DatasetError("inline 'files' must map paths to text content")
        meta["files"] = files
    elif files not in (None, "", {}):
        raise DatasetError(FILES_FORMS)
    as_text = lambda v: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return {"task": as_text(task), "answer": None if answer is None else as_text(answer), "meta": meta}


def normalize_items(rows: list, base_dir: Path | None = None, defaults: dict | None = None) -> list[dict]:
    out = []
    for i, r in enumerate(rows, 1):
        try:
            out.append(normalize_item(r, base_dir, defaults))
        except DatasetError as e:
            raise DatasetError(f"item {i}: {e}")
    return out


def parse_dataset(filename: str, raw: bytes, base_dir: Path | None = None, defaults: dict | None = None) -> list[dict]:
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
    return normalize_items(rows, base_dir, defaults)
