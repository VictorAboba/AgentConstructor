"""Static checks of a graph definition, used before saving from MCP/REST and shown to the user."""
from __future__ import annotations

from collections import defaultdict

from ..tools.builtin import BUILTIN_TOOLS

NODE_TYPES = {"input", "agent", "vote", "board", "output"}
EDGE_KINDS = {"flow", "conditional", "feedback", "handoff", "delegate", "message", "subscribe"}


def _posters(data: dict, board: str, types: dict) -> set[str]:
    """Nodes that can publish to a board: message edges into it (or two-way ones) and flow edges into it."""
    out = set()
    for e in data.get("edges", []):
        d = e.get("data") or {}
        kind, s, t = d.get("kind", "flow"), e.get("source"), e.get("target")
        if kind in ("flow", "conditional", "feedback", "message") and t == board:
            out.add(s)
        elif kind == "message" and s == board and d.get("bidirectional") and types.get(t) == "agent":
            out.add(t)
    return out


def validate_graph(data: dict, models: dict[str, dict]) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    nodes = {n.get("id"): n for n in data.get("nodes", [])}
    types = {nid: n.get("type") for nid, n in nodes.items()}
    label = lambda nid: ((nodes.get(nid) or {}).get("data") or {}).get("label") or nid

    for nid, n in nodes.items():
        if not nid:
            errors.append("a node has no id")
        if types[nid] not in NODE_TYPES:
            errors.append(f"node {label(nid)}: unknown type {types[nid]!r} (expected one of {sorted(NODE_TYPES)})")
        if types[nid] == "agent":
            d = n.get("data") or {}
            if not d.get("model_id"):
                errors.append(f"agent {label(nid)}: no model_id")
            elif d["model_id"] not in models:
                errors.append(f"agent {label(nid)}: unknown model_id {d['model_id']!r}")
            unknown = [t for t in d.get("tools") or [] if t not in BUILTIN_TOOLS]
            if unknown:
                warnings.append(f"agent {label(nid)}: unknown tools ignored: {unknown}")
    if "input" not in types.values():
        errors.append("graph needs an input node")
    if "agent" not in types.values():
        errors.append("graph needs at least one agent node")
    if "output" not in types.values():
        warnings.append("no output node: the last agent output will be used as the answer")

    adj: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, int] = defaultdict(int)
    for e in data.get("edges", []):
        s, t = e.get("source"), e.get("target")
        kind = (e.get("data") or {}).get("kind", "flow")
        name = f"edge {label(s)} → {label(t)}"
        if s not in nodes or t not in nodes:
            errors.append(f"{name}: references a missing node")
            continue
        if kind not in EDGE_KINDS:
            errors.append(f"{name}: unknown kind {kind!r} (expected one of {sorted(EDGE_KINDS)})")
            continue
        ts, tt = types[s], types[t]
        if kind in ("handoff", "delegate") and (ts != "agent" or tt != "agent"):
            errors.append(f"{name}: {kind} must connect two agents")
        if kind == "message" and not ({ts, tt} <= {"agent", "board"} and "agent" in (ts, tt)):
            errors.append(f"{name}: message edges connect agents with agents or boards")
        if kind == "subscribe" and {ts, tt} != {"agent", "board"}:
            errors.append(f"{name}: subscribe connects an agent with a board")
        elif kind == "subscribe":
            board = t if tt == "board" else s
            authors = (e.get("data") or {}).get("authors") or []
            missing = [a for a in authors if a not in nodes]
            if missing:
                errors.append(f"{name}: authors reference missing nodes {missing}")
            silent = [label(a) for a in authors if a in nodes and a not in _posters(data, board, types)]
            if silent:
                warnings.append(f"{name}: {silent} cannot post to {label(board)}, their posts will never arrive")
        if tt == "input":
            errors.append(f"{name}: input nodes cannot receive edges")
        if ts == "output":
            errors.append(f"{name}: output nodes cannot send edges")
        adj[s].add(t)
        incoming[t] += 1
        if kind in ("message", "subscribe"):
            adj[t].add(s)  # reachability: both ends take part in the conversation
    for nid, ty in types.items():
        if ty == "output" and not incoming[nid]:
            warnings.append(f"output {label(nid)} has no incoming edge")

    reach, stack = set(), [nid for nid, ty in types.items() if ty == "input"]
    while stack:
        nid = stack.pop()
        if nid not in reach:
            reach.add(nid)
            stack.extend(adj[nid])
    unreached = [label(nid) for nid in nodes if nid not in reach]
    if unreached:
        warnings.append(f"not reachable from an input: {unreached}")
    return {"ok": not errors, "errors": errors, "warnings": warnings}
