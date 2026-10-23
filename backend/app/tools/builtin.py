"""Built-in agent tools. Each returns (text_result, is_error)."""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..providers import ToolSpec
from .sandbox import Sandbox, SandboxError

OUTPUT_LIMIT = 12000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".sandbox", ".mypy_cache"}


def truncate(text: str, limit: int = OUTPUT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    return text[:head] + f"\n…[{len(text) - limit} chars omitted]…\n" + text[-(limit - head):]


def _fmt_exec(r) -> str:
    parts = [f"exit_code: {r.exit_code}" + (" (timed out)" if r.timed_out else "")]
    if r.stdout:
        parts.append("--- stdout ---\n" + r.stdout.rstrip())
    if r.stderr:
        parts.append("--- stderr ---\n" + r.stderr.rstrip())
    return truncate("\n".join(parts))


async def t_shell(sb: Sandbox, a: dict):
    cmd = a.get("command")
    if not cmd:
        return "missing 'command'", True
    r = await sb.exec(cmd, _timeout(a, sb))
    return _fmt_exec(r), r.exit_code != 0


async def t_python(sb: Sandbox, a: dict):
    code = a.get("code")
    if not code:
        return "missing 'code'", True
    r = await sb.run_python(code, _timeout(a, sb))
    return _fmt_exec(r), r.exit_code != 0


def _timeout(a: dict, sb: Sandbox) -> int:
    try:
        return max(1, min(int(a.get("timeout") or sb.cfg.timeout), 600))
    except (TypeError, ValueError):
        return sb.cfg.timeout


async def t_read_file(sb: Sandbox, a: dict):
    p = sb.resolve(a.get("path"))
    if not p.is_file():
        return f"not a file: {a.get('path')}", True
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    offset = max(int(a.get("offset") or 1), 1)
    limit = max(int(a.get("limit") or 400), 1)
    chunk = lines[offset - 1: offset - 1 + limit]
    body = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(chunk, start=offset))
    tail = f"\n[lines {offset}-{offset + len(chunk) - 1} of {len(lines)}]" if len(lines) > len(chunk) else ""
    return truncate(body + tail) or "(empty file)", False


async def t_write_file(sb: Sandbox, a: dict):
    p = sb.resolve(a.get("path"))
    content = a.get("content")
    if content is None:
        return "missing 'content'", True
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content.encode('utf-8'))} bytes to {p.relative_to(sb.root).as_posix()}", False


async def t_edit_file(sb: Sandbox, a: dict):
    p = sb.resolve(a.get("path"))
    if not p.is_file():
        return f"not a file: {a.get('path')}", True
    old, new = a.get("old_str"), a.get("new_str", "")
    if not old:
        return "missing 'old_str'", True
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old)
    if count == 0:
        return "old_str not found in file", True
    if count > 1 and not a.get("replace_all"):
        return f"old_str occurs {count} times; make it unique or set replace_all=true", True
    text = text.replace(old, new) if a.get("replace_all") else text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    return f"replaced {count if a.get('replace_all') else 1} occurrence(s) in {p.relative_to(sb.root).as_posix()}", False


async def t_list_dir(sb: Sandbox, a: dict):
    base = sb.resolve(a.get("path"))
    if not base.is_dir():
        return f"not a directory: {a.get('path')}", True
    depth = max(1, min(int(a.get("depth") or 2), 6))
    out: list[str] = []

    def walk(d, level):
        if len(out) > 400:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except OSError:
            return
        for e in entries:
            if e.name in SKIP_DIRS:
                continue
            rel = e.relative_to(sb.root).as_posix()
            if e.is_dir():
                out.append(f"{'  ' * level}{rel}/")
                if level + 1 < depth:
                    walk(e, level + 1)
            else:
                out.append(f"{'  ' * level}{rel}  ({e.stat().st_size} B)")

    walk(base, 0)
    return ("\n".join(out[:400]) + ("\n…" if len(out) > 400 else "")) or "(empty directory)", False


async def t_search(sb: Sandbox, a: dict):
    try:
        rx = re.compile(a.get("pattern") or "")
    except re.error as e:
        return f"invalid regex: {e}", True
    base = sb.resolve(a.get("path"))
    glob = a.get("glob") or "*"
    hits: list[str] = []
    files = [base] if base.is_file() else (f for f in base.rglob("*") if f.is_file())
    for f in files:
        if any(part in SKIP_DIRS for part in f.relative_to(sb.root).parts):
            continue
        if not fnmatch.fnmatch(f.name, glob):
            continue
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(sb.root).as_posix()}:{i}: {line.strip()[:300]}")
                    if len(hits) >= 200:
                        break
        except OSError:
            continue
        if len(hits) >= 200:
            break
    return "\n".join(hits) or "no matches", False


async def t_think(sb: Sandbox, a: dict):
    return "noted", False


@dataclass
class ToolDef:
    spec: ToolSpec
    fn: Callable[[Sandbox, dict], Awaitable[tuple[str, bool]]] | None
    category: str


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}
I = {"type": "integer"}

BUILTIN_TOOLS: dict[str, ToolDef] = {
    "shell": ToolDef(ToolSpec("shell", "Run a shell command in the sandbox workspace (cwd = workspace root). Returns exit code, stdout and stderr.",
                              _obj({"command": {**S, "description": "Shell command"}, "timeout": {**I, "description": "Seconds, default 60"}}, ["command"])),
                     t_shell, "environment"),
    "python": ToolDef(ToolSpec("python", "Execute a Python script in the sandbox workspace and return its output. Print what you need to see.",
                               _obj({"code": S, "timeout": I}, ["code"])), t_python, "environment"),
    "read_file": ToolDef(ToolSpec("read_file", "Read a text file from the workspace with line numbers.",
                                  _obj({"path": S, "offset": {**I, "description": "1-based start line"}, "limit": {**I, "description": "Max lines (default 400)"}}, ["path"])),
                         t_read_file, "files"),
    "write_file": ToolDef(ToolSpec("write_file", "Create or overwrite a file in the workspace.",
                                   _obj({"path": S, "content": S}, ["path", "content"])), t_write_file, "files"),
    "edit_file": ToolDef(ToolSpec("edit_file", "Replace an exact string in a file. old_str must be unique unless replace_all is true.",
                                  _obj({"path": S, "old_str": S, "new_str": S, "replace_all": {"type": "boolean"}}, ["path", "old_str", "new_str"])),
                         t_edit_file, "files"),
    "list_dir": ToolDef(ToolSpec("list_dir", "List files and directories in the workspace.",
                                 _obj({"path": {**S, "description": "Directory, default '.'"}, "depth": {**I, "description": "Recursion depth, default 2"}}, [])),
                        t_list_dir, "files"),
    "search": ToolDef(ToolSpec("search", "Regex search over file contents in the workspace (like grep -rn).",
                               _obj({"pattern": S, "path": S, "glob": {**S, "description": "Filename glob, e.g. *.py"}}, ["pattern"])),
                      t_search, "files"),
    "think": ToolDef(ToolSpec("think", "Think step by step before acting: write down reasoning or a plan. Has no side effects.",
                              _obj({"thought": S}, ["thought"])), t_think, "reasoning"),
}

DEFAULT_AGENT_TOOLS = ["shell", "read_file", "write_file", "edit_file", "list_dir", "search"]


async def run_builtin(name: str, sb: Sandbox, args: dict) -> tuple[str, bool]:
    tool = BUILTIN_TOOLS.get(name)
    if tool is None or tool.fn is None:
        return f"unknown tool: {name}", True
    if "_invalid_json" in args:
        return f"arguments were not valid JSON: {args['_invalid_json'][:500]}", True
    try:
        return await tool.fn(sb, args)
    except SandboxError as e:
        return str(e), True
    except (OSError, ValueError, TypeError) as e:
        return f"{type(e).__name__}: {e}", True
