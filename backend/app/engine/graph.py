"""Graph execution: dataflow scheduling of agent nodes connected by typed edges.

Node types
  input   — emits the task text when the run starts
  agent   — LLM + tools loop; an activation ends when the model replies without calling tools
  vote    — no LLM: majority vote over incoming answers (self-consistency / ensembles)
  board   — message board: agents post to it, subscribers receive every post
  output  — collects the final answer (last message received)

Edge kinds
  flow        — source output is delivered to target (into a board: the output is posted)
  conditional — delivered only if the condition matches the source output
  feedback    — conditional back-edge allowed to form cycles, limited by max_iterations
  handoff     — source gets a `handoff_to_<target>` tool; delivered only if the agent calls it
                (and then replaces all other outgoing deliveries; the turn ends)
  delegate    — source gets an `ask_<target>` tool: target runs synchronously as a sub-agent and
                its output returns as the tool result (manager → worker)
  message     — source gets a `message_<target>` tool to write to the target at any moment without
                ending its turn; `bidirectional` gives the target the reverse tool. To a board it
                grants posting (`post_<board>`); a two-way message edge to a board also subscribes.
  subscribe   — agent ↔ board (either direction): the agent receives the posts of the board; `authors`
                (node ids) narrows it to posts by those nodes, empty = every post

Scheduling: a node with join="all" waits until none of its ancestors (via flow/conditional/handoff
edges) is running or has queued input, then consumes everything queued at once. join="any" fires
per arrival. Direct messages and board posts reach a busy agent before its next model call; an idle
agent is activated by them. Parallel branches run concurrently.
"""
from __future__ import annotations

import asyncio
import contextvars
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..providers import LLMParams, ProviderError, ToolSpec, get_provider
from ..tools.builtin import BUILTIN_TOOLS, DEFAULT_AGENT_TOOLS, run_builtin
from ..tools.sandbox import Sandbox
from .evaluator import extract_answer, normalize
from .tracer import Tracer

DATAFLOW_KINDS = {"flow", "conditional", "handoff"}
LIVE_KINDS = {"direct", "board"}  # messages that may be injected into a running activation
ENV_TOOLS = {"shell", "python", "read_file", "write_file", "edit_file", "list_dir", "search"}
_delegate_depth: contextvars.ContextVar[int] = contextvars.ContextVar("delegate_depth", default=0)


class GraphError(Exception):
    pass


@dataclass
class Message:
    source: str
    source_label: str
    content: str
    kind: str


@dataclass
class NodeResult:
    output: str | None
    handoff: str | None = None  # target node id
    handoff_message: str | None = None
    error: str | None = None
    status: str = "ok"


@dataclass
class Settings:
    max_activations: int = 40
    timeout_s: int = 900
    max_delegate_depth: int = 3

    @classmethod
    def from_dict(cls, d: dict | None) -> "Settings":
        d = d or {}
        return cls(**{k: int(v) for k, v in d.items() if k in cls.__dataclass_fields__ and v is not None})


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return s or "agent"


def check_condition(cond: dict | None, text: str) -> bool:
    cond = cond or {}
    ctype, value = cond.get("type", "always"), cond.get("value", "") or ""
    if ctype in ("always", "") or not value and ctype != "regex":
        return True
    if ctype == "contains":
        return value.lower() in (text or "").lower()
    if ctype == "not_contains":
        return value.lower() not in (text or "").lower()
    if ctype == "regex":
        try:
            return re.search(value, text or "", re.S) is not None
        except re.error:
            return False
    return True


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


class AgentRuntime:
    def __init__(self, run: "GraphRun", node: dict):
        self.run = run
        self.node = node
        self.data = node.get("data") or {}
        self.label = self.data.get("label") or node["id"]
        self.history: list[dict] = []
        self.lock = asyncio.Lock()
        self.activations = 0
        self.busy = False
        model_id = self.data.get("model_id")
        if not model_id or model_id not in run.models:
            raise GraphError(f"agent '{self.label}' has no valid model selected")
        self.model_cfg = run.models[model_id]
        self.provider = get_provider(self.model_cfg)
        self.params = LLMParams(
            max_tokens=int(self.data.get("max_tokens") or 16000),
            temperature=self.data.get("temperature") if self.data.get("temperature") not in ("", None) else None,
            effort=self.data.get("effort") or None,
            extra=(self.model_cfg.get("extra") or {}).get("body") or {},
        )
        self.max_steps = int(self.data.get("max_steps") or 20)
        self._build_tools()

    def _build_tools(self) -> None:
        names = self.data.get("tools")
        if names is None:
            names = DEFAULT_AGENT_TOOLS
        self.tool_specs: list[ToolSpec] = [BUILTIN_TOOLS[n].spec for n in names if n in BUILTIN_TOOLS]
        self.handoffs: dict[str, str] = {}
        self.delegates: dict[str, str] = {}
        self.messages_to: dict[str, tuple[str, str]] = {}  # tool → (target agent, edge id)
        self.posts_to: dict[str, tuple[str, str]] = {}  # tool → (board, edge id)
        self.reads: dict[str, str] = {}  # tool → board
        used = {t.name for t in self.tool_specs}
        nid = self.node["id"]

        def unique(base: str) -> str:
            name, i = base[:60], 2
            while name in used:
                name, i = f"{base[:56]}_{i}", i + 1
            used.add(name)
            return name

        for e in self.run.out_edges[nid]:
            if e["kind"] not in ("handoff", "delegate"):
                continue
            tlabel = self.run.label(e["target"])
            desc = (e.get("label") or "").strip()
            if e["kind"] == "handoff":
                name = unique("handoff_to_" + _slug(tlabel))
                self.handoffs[name] = e["target"]
                self.tool_specs.append(ToolSpec(name, f"Transfer control to agent '{tlabel}' and end your turn. {desc}".strip(),
                                                _obj({"message": {"type": "string", "description": "What to pass to the next agent"}}, ["message"])))
            else:
                name = unique("ask_" + _slug(tlabel))
                self.delegates[name] = e["target"]
                self.tool_specs.append(ToolSpec(name, f"Ask agent '{tlabel}' to perform a sub-task; returns its answer. {desc}".strip(),
                                                _obj({"task": {"type": "string", "description": "Self-contained sub-task"}}, ["task"])))

        for target, edge in self.run.message_links[nid]:
            tlabel = self.run.label(target)
            desc = (edge.get("label") or "").strip()
            name = unique("message_" + _slug(tlabel))
            self.messages_to[name] = (target, edge["id"])
            self.tool_specs.append(ToolSpec(
                name, f"Send a message to agent '{tlabel}'. Does not end your turn; replies arrive as new messages. {desc}".strip(),
                _obj({"text": {"type": "string", "description": "Message text"}}, ["text"])))

        for board, edge in self.run.post_links[nid]:
            blabel = self.run.label(board)
            name = unique("post_" + _slug(blabel))
            self.posts_to[name] = (board, edge["id"])
            self.tool_specs.append(ToolSpec(
                name, f"Post a message to the board '{blabel}'; every subscriber receives it. Does not end your turn.",
                _obj({"text": {"type": "string", "description": "Post text"}}, ["text"])))
        for board in sorted({b for b, _ in self.run.post_links[nid]} | {b for b, _ in self.run.subscriptions_of[nid]}):
            name = unique("read_" + _slug(self.run.label(board)))
            self.reads[name] = board
            self.tool_specs.append(ToolSpec(
                name, f"Read recent posts of the board '{self.run.label(board)}'.",
                _obj({"last": {"type": "integer", "description": "How many recent posts (default 20)"}}, [])))

    def system_prompt(self) -> str:
        parts = [self.data.get("system_prompt") or "You are a helpful agent."]
        if self.data.get("auto_context", True):
            ctx = [f'You are "{self.label}", one agent in a multi-agent system.']
            if any(t.name in ENV_TOOLS for t in self.tool_specs):
                ctx.append("You work in a sandboxed workspace directory shared with the other agents of this run; use paths relative to it.")
            if self.handoffs:
                ctx.append("You may transfer control with: " + ", ".join(self.handoffs) + ".")
            if self.delegates:
                ctx.append("You may delegate sub-tasks with: " + ", ".join(self.delegates) + ".")
            if self.messages_to:
                ctx.append("You may write to other agents with: " + ", ".join(self.messages_to) + ".")
            if self.posts_to or self.reads:
                ctx.append("Message boards: " + ", ".join([*self.posts_to, *self.reads]) + ".")
            for board, _ in self.run.subscriptions_of[self.node["id"]]:
                authors = self.run.sub_authors[(board, self.node["id"])]
                who = "new posts by " + ", ".join(sorted(self.run.label(a) for a in authors)) if authors is not None else "all new posts"
                ctx.append(f"You are subscribed to the board '{self.run.label(board)}': you receive {who} as messages.")
            if self.messages_to or self.posts_to or self.run.subscriptions_of[self.node["id"]] or self.run.message_links_in[self.node["id"]]:
                ctx.append("Messages from other agents may arrive while you work; they appear as new user messages.")
            ctx.append("When you are done, reply with your complete final output without calling any tools — that ends your turn.")
            parts.append("\n".join(ctx))
        return "\n\n".join(parts)

    def _compose_input(self, messages: list[Message], first_of_activation: bool = True) -> str:
        chunks = []
        include_task = self.data.get("include_task", True)
        if first_of_activation and (self.activations == 0 or self.data.get("memory") == "fresh") and include_task:
            chunks.append(f"Task:\n{self.run.task}")
        for m in messages:
            if m.kind == "input":
                if not include_task:
                    chunks.append(f"Task:\n{m.content}")
                continue
            tag = {"delegate": "Request from", "handoff": "Handoff from", "feedback": "Feedback from",
                   "direct": "Message from", "board": "Board post"}.get(m.kind, "Message from")
            chunks.append(f"{tag} {m.source_label}:\n{m.content}")
        return "\n\n".join(chunks) or "Continue."

    async def activate(self, messages: list[Message], parent_id: str | None) -> NodeResult:
        async with self.lock:
            self.busy = True
            try:
                return await self._activate(messages, parent_id)
            finally:
                self.busy = False
                self.run.requeue_live(self.node["id"])

    async def _activate(self, messages: list[Message], parent_id: str | None) -> NodeResult:
        tr = self.run.tracer
        nid = self.node["id"]
        if self.data.get("memory") == "fresh":
            self.history = []
            self.run.last_seen[nid] = 0
        messages = [*messages, *self.run.take_live(nid)]
        user_text = self._compose_input(messages)
        self.activations += 1
        system = self.system_prompt()
        node_span = tr.start("node", self.label, parent_id, nid, {
            "activation": self.activations, "input": user_text, "model": self.model_cfg["model"],
            "provider": self.model_cfg["provider"], "inbox": [m.__dict__ for m in messages],
            "system": system, "tools": [t.name for t in self.tool_specs], "memory": self.data.get("memory", "persistent"),
            "history_messages": len(self.history),
        })
        self.history.append({"role": "user", "content": user_text})
        result = NodeResult(output=None)
        last_text = ""
        steps = 0
        try:
            for steps in range(1, self.max_steps + 1):
                if steps > 1:
                    live = self.run.take_live(nid)
                    if live:
                        self.history.append({"role": "user", "content": self._compose_input(live, first_of_activation=False)})
                        tr.event("inject", f"{self.label} receives {len(live)} message(s)", node_span.id, nid,
                                 {"messages": [m.__dict__ for m in live]})
                llm_span = tr.start("llm", self.model_cfg["name"], node_span.id, nid, {
                    "step": steps, "model": self.model_cfg["model"],
                    "system": system if steps == 1 else None,
                    "tools": [t.name for t in self.tool_specs] if steps == 1 else None,
                    "new_messages": _strip_native(self.history[self.run.last_seen.get(nid, 0):]),
                })
                try:
                    resp = await self.provider.complete(system, self.history, self.tool_specs, self.params)
                except ProviderError as e:
                    tr.end(llm_span, "error", {"error": str(e)})
                    raise
                cost = self.provider.cost(resp)
                llm_span.input_tokens, llm_span.output_tokens, llm_span.cost = resp.input_tokens, resp.output_tokens, cost
                tr.end(llm_span, "ok" if resp.stop_reason != "refusal" else "error", {
                    "text": resp.text, "tool_calls": resp.tool_calls, "reasoning": resp.reasoning,
                    "stop_reason": resp.stop_reason, "served_by": resp.model, "cached_tokens": resp.cached_tokens,
                    "estimated_usage": resp.estimated_usage, "notes": resp.notes or None,
                })
                if resp.reasoning:
                    # The model reasoned during this call: shown at the call's start, before its answer.
                    tr.event("thought", f"{self.label} thinks", llm_span.id, nid,
                             {"text": resp.reasoning, "source": "model"}, at=llm_span.started_at + 1e-4)
                tr.record_llm(nid, resp.input_tokens, resp.output_tokens, resp.cached_tokens, cost)
                self.history.append(resp.assistant_message(self.provider.name))
                self.run.last_seen[nid] = len(self.history)  # next LLM span shows what was added after this
                if resp.text:
                    last_text = resp.text
                if resp.stop_reason == "refusal":
                    result = NodeResult(output=resp.text or "[refused]", status="refusal")
                    break
                if not resp.tool_calls:
                    result = NodeResult(output=resp.text)
                    break
                if await self._run_tools(resp.tool_calls, node_span.id, result):
                    break
            else:
                result = NodeResult(output=last_text, status="max_steps")
        except ProviderError as e:
            result = NodeResult(output=None, error=str(e), status="error")
        except asyncio.CancelledError:
            tr.end(node_span, "cancelled")
            raise
        duration = tr.end(node_span, "ok" if result.status == "ok" else ("error" if result.error else "warn"), {
            "output": result.output, "status": result.status, "steps": steps, "error": result.error,
            "handoff": result.handoff,
        })
        tr.record_activation(nid, duration, error=bool(result.error))
        return result

    async def _run_tools(self, calls: list[dict], parent_id: str, result: NodeResult) -> bool:
        """Runs the tool calls of one model response; returns True if the turn ended (handoff)."""
        tr = self.run.tracer
        nid = self.node["id"]
        ended = False
        for tc in calls:
            name, args = tc["name"], tc.get("arguments") or {}
            tr.record_tool(nid)
            span = tr.start("tool", name, parent_id, nid, {"arguments": args})
            is_error = False
            if ended:
                out, is_error = "skipped: turn already ended by a previous call", True
            elif name in self.handoffs:
                target = self.handoffs[name]
                result.handoff = target
                result.handoff_message = str(args.get("message", ""))
                result.output = result.handoff_message
                out, ended = f"Control transferred to {self.run.label(target)}.", True
            elif name in self.delegates:
                out, is_error = await self.run.delegate(nid, self.delegates[name], str(args.get("task", "")), span.id)
            elif name in self.messages_to:
                target, edge_id = self.messages_to[name]
                out, is_error = self.run.send_direct(nid, target, str(args.get("text", "")), edge_id)
            elif name in self.posts_to:
                board, edge_id = self.posts_to[name]
                out, is_error = self.run.post(nid, board, str(args.get("text", "")), edge_id)
            elif name in self.reads:
                out, is_error = self.run.read_board(self.reads[name], args.get("last")), False
            elif name in {t.name for t in self.tool_specs}:
                if name == "think":
                    tr.event("thought", f"{self.label} thinks", span.id, nid, {"text": str(args.get("thought", "")), "source": "think tool"})
                out, is_error = await run_builtin(name, self.run.sandbox, args)
            else:
                out, is_error = f"tool not available: {name}", True
            tr.end(span, "error" if is_error else "ok", {"result": out})
            self.history.append({"role": "tool", "tool_call_id": tc["id"], "name": name, "content": out, "is_error": is_error})
        return ended


def _strip_native(msgs: list[dict]) -> list[dict]:
    return [{k: v for k, v in m.items() if k not in ("native", "provider")} for m in msgs]


@dataclass
class GraphRun:
    graph: dict
    task: str
    tracer: Tracer
    sandbox: Sandbox
    models: dict[str, dict]
    settings: Settings = field(init=False)

    def __post_init__(self):
        self.settings = Settings.from_dict(self.graph.get("settings"))
        self.nodes: dict[str, dict] = {n["id"]: n for n in self.graph.get("nodes", [])}
        self.edges: list[dict] = []
        for e in self.graph.get("edges", []):
            if e.get("source") in self.nodes and e.get("target") in self.nodes:
                d = e.get("data") or {}
                self.edges.append({"id": e["id"], "source": e["source"], "target": e["target"],
                                   "kind": d.get("kind", "flow"), "condition": d.get("condition"),
                                   "max_iterations": int(d.get("max_iterations") or 3), "label": d.get("label", ""),
                                   "bidirectional": bool(d.get("bidirectional")),
                                   "authors": list(d.get("authors") or [])})  # unknown ids stay: they just never post
        self.out_edges: dict[str, list[dict]] = defaultdict(list)
        for e in self.edges:
            self.out_edges[e["source"]].append(e)
        self._index_messaging()
        self.ancestors = self._ancestors()
        self.inbox: dict[str, list[Message]] = defaultdict(list)
        self.live: dict[str, list[Message]] = defaultdict(list)
        self.boards: dict[str, list[dict]] = defaultdict(list)
        self.wake = asyncio.Event()
        self.feedback_count: Counter = Counter()
        self.outputs: list[Message] = []
        self.last_agent_output: str | None = None
        self.errors: list[str] = []
        self.activations = 0
        self.last_seen: dict[str, int] = {}
        self.limit_hit = False
        self.agents: dict[str, AgentRuntime] = {}
        for nid, n in self.nodes.items():
            if n.get("type") == "agent":
                self.agents[nid] = AgentRuntime(self, n)

    def type_of(self, nid: str) -> str | None:
        return self.nodes[nid].get("type")

    def label(self, nid: str) -> str:
        n = self.nodes.get(nid) or {}
        return (n.get("data") or {}).get("label") or nid

    def _index_messaging(self) -> None:
        """Who may message whom, who posts to and who is subscribed to which board."""
        self.message_links: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.message_links_in: dict[str, list[str]] = defaultdict(list)
        self.post_links: dict[str, list[tuple[str, dict]]] = defaultdict(list)
        self.subscribers: dict[str, list[tuple[str, dict]]] = defaultdict(list)  # board → [(agent, edge)]
        self.subscriptions_of: dict[str, list[tuple[str, dict]]] = defaultdict(list)  # agent → [(board, edge)]
        # (board, agent) → authors whose posts are delivered; None = everyone. Several edges between
        # the same pair add up: any edge without a filter wins.
        self.sub_authors: dict[tuple[str, str], set[str] | None] = {}

        def subscribe(agent: str, board: str, edge: dict, authors: list[str] | None = None) -> None:
            key = (board, agent)
            if key not in self.sub_authors:
                self.subscribers[board].append((agent, edge))
                self.subscriptions_of[agent].append((board, edge))
                self.sub_authors[key] = set(authors) if authors else None
            elif self.sub_authors[key] is not None:
                self.sub_authors[key] = self.sub_authors[key] | set(authors) if authors else None

        for e in self.edges:
            s, t, kind = e["source"], e["target"], e["kind"]
            ts, tt = self.type_of(s), self.type_of(t)
            if kind == "message":
                pairs = [(s, t)] + ([(t, s)] if e["bidirectional"] else [])
                for a, b in pairs:
                    if self.type_of(a) == "agent" and self.type_of(b) == "agent":
                        self.message_links[a].append((b, e))
                        self.message_links_in[b].append(a)
                    elif self.type_of(a) == "agent" and self.type_of(b) == "board":
                        self.post_links[a].append((b, e))
                    elif self.type_of(a) == "board" and self.type_of(b) == "agent":
                        subscribe(b, a, e)
            elif kind == "subscribe":
                if ts == "agent" and tt == "board":
                    subscribe(s, t, e, e["authors"])
                elif ts == "board" and tt == "agent":
                    subscribe(t, s, e, e["authors"])
            elif kind == "flow" and ts == "board" and tt == "agent":
                subscribe(t, s, e)

    def _ancestors(self) -> dict[str, set[str]]:
        parents: dict[str, set[str]] = defaultdict(set)
        for e in self.edges:
            if e["kind"] in DATAFLOW_KINDS and self.type_of(e["source"]) != "board":
                parents[e["target"]].add(e["source"])
        result = {}
        for nid in self.nodes:
            seen, stack = set(), list(parents[nid])
            while stack:
                p = stack.pop()
                if p not in seen:
                    seen.add(p)
                    stack.extend(parents[p])
            seen.discard(nid)
            result[nid] = seen
        return result

    # ---- routing -----------------------------------------------------------------------
    def _enqueue(self, dst: str, msg: Message) -> None:
        agent = self.agents.get(dst)
        if msg.kind in LIVE_KINDS and agent is not None and agent.busy:
            self.live[dst].append(msg)
        else:
            self.inbox[dst].append(msg)
            self.wake.set()

    def take_live(self, nid: str) -> list[Message]:
        msgs, self.live[nid] = self.live[nid], []
        return msgs

    def requeue_live(self, nid: str) -> None:
        """Messages that arrived during an activation's last model call start a new activation."""
        if self.live[nid]:
            self.inbox[nid].extend(self.take_live(nid))
        self.wake.set()  # also re-check inbox messages held back while it ran as a delegate

    def _deliver(self, edge: dict, content: str, kind: str) -> None:
        src, dst = edge["source"], edge["target"]
        if self.type_of(dst) == "board":
            self.post(src, dst, content, edge["id"])
            return
        msg = Message(src, self.label(src), content, kind)
        self.tracer.event("message", f"{self.label(src)} → {self.label(dst)}", node_id=dst, data={
            "edge_id": edge["id"], "kind": kind, "from": src, "to": dst, "content": content})
        if self.type_of(dst) == "output":
            self.outputs.append(msg)
        else:
            self._enqueue(dst, msg)

    def send_direct(self, src: str, dst: str, text: str, edge_id: str) -> tuple[str, bool]:
        if not text.strip():
            return "empty message not sent", True
        self.tracer.event("message", f"{self.label(src)} → {self.label(dst)}", node_id=dst, data={
            "edge_id": edge_id, "kind": "direct", "from": src, "to": dst, "content": text})
        self._enqueue(dst, Message(src, self.label(src), text, "direct"))
        return f"Message delivered to {self.label(dst)}.", False

    def post(self, src: str, board: str, text: str, edge_id: str) -> tuple[str, bool]:
        if not text.strip():
            return "empty post not published", True
        self.boards[board].append({"from": self.label(src), "text": text, "t": time.time()})
        self.tracer.event("message", f"{self.label(src)} → {self.label(board)}", node_id=board, data={
            "edge_id": edge_id, "kind": "post", "from": src, "to": board, "content": text,
            "post_index": len(self.boards[board])})
        receivers = []
        for agent, edge in self.subscribers[board]:
            authors = self.sub_authors[(board, agent)]
            if agent == src or (authors is not None and src not in authors):
                continue
            self.tracer.event("message", f"{self.label(board)} → {self.label(agent)}", node_id=agent, data={
                "edge_id": edge["id"], "kind": "board", "from": board, "to": agent, "content": text,
                "author": self.label(src)})
            self._enqueue(agent, Message(board, f"{self.label(board)} / {self.label(src)}", text, "board"))
            receivers.append(self.label(agent))
        return f"Posted to {self.label(board)}; delivered to {', '.join(receivers) or 'no subscribers'}.", False

    def read_board(self, board: str, last) -> str:
        try:
            n = max(1, min(int(last or 20), 200))
        except (TypeError, ValueError):
            n = 20
        posts = self.boards[board][-n:]
        if not posts:
            return "The board is empty."
        start = len(self.boards[board]) - len(posts) + 1
        return "\n\n".join(f"#{i} {p['from']}:\n{p['text']}" for i, p in enumerate(posts, start))

    def route(self, nid: str, res: NodeResult) -> None:
        if res.output is None:
            return
        if self.type_of(nid) == "agent":
            self.last_agent_output = res.output
        for e in self.out_edges[nid]:
            kind = e["kind"]
            if res.handoff:
                if kind == "handoff" and e["target"] == res.handoff:
                    self._deliver(e, res.handoff_message or res.output, "handoff")
                continue
            if kind == "flow":
                self._deliver(e, res.output, "input" if self.type_of(nid) == "input" else "flow")
            elif kind == "conditional" and check_condition(e["condition"], res.output):
                self._deliver(e, res.output, "conditional")
            elif kind == "feedback" and check_condition(e["condition"], res.output):
                if self.feedback_count[e["id"]] < e["max_iterations"]:
                    self.feedback_count[e["id"]] += 1
                    self._deliver(e, res.output, "feedback")
                else:
                    self.tracer.event("limit", f"feedback limit {e['max_iterations']} reached", node_id=nid,
                                      data={"edge_id": e["id"]}, status="warn")

    async def delegate(self, caller: str, target: str, task: str, parent_id: str) -> tuple[str, bool]:
        depth = _delegate_depth.get()
        if depth >= self.settings.max_delegate_depth:
            return "delegation depth limit reached", True
        if self.activations >= self.settings.max_activations:
            return "activation limit reached", True
        if self.type_of(target) != "agent":
            return "delegate target is not an agent", True
        self.activations += 1
        token = _delegate_depth.set(depth + 1)
        try:
            res = await self.agents[target].activate([Message(caller, self.label(caller), task, "delegate")], parent_id)
        finally:
            _delegate_depth.reset(token)
        if res.error:
            return f"sub-agent failed: {res.error}", True
        return res.output or "(no output)", False

    # ---- node activation ---------------------------------------------------------------
    async def activate(self, nid: str, messages: list[Message]) -> NodeResult:
        ntype = self.type_of(nid)
        if ntype == "agent":
            return await self.agents[nid].activate(messages, None)
        if ntype == "vote":
            return self._vote(nid, messages)
        # pass-through for unknown node kinds
        return NodeResult(output="\n\n".join(m.content for m in messages))

    def _vote(self, nid: str, messages: list[Message]) -> NodeResult:
        answers = [(extract_answer(m.content), m) for m in messages if m.content]
        counts = Counter(normalize(a) for a, _ in answers)
        if not counts:
            return NodeResult(output="")
        winner_norm, votes = counts.most_common(1)[0]
        winner = next(a for a, _ in answers if normalize(a) == winner_norm)
        self.tracer.event("vote", f"{self.label(nid)}: {votes}/{len(answers)}", node_id=nid, data={
            "candidates": [{"from": m.source_label, "answer": a} for a, m in answers],
            "tally": dict(counts), "winner": winner})
        self.tracer.record_activation(nid, 0)
        return NodeResult(output=f"<answer>{winner}</answer>")

    def _ready(self, running: dict) -> list[str]:
        busy = set(running) | {n for n, q in self.inbox.items() if q}
        ready = []
        for nid, queue in self.inbox.items():
            if not queue or nid in running:
                continue
            agent = self.agents.get(nid)
            if agent is not None and agent.busy:  # running as someone's delegate
                continue
            join = (self.nodes[nid].get("data") or {}).get("join", "all")
            if join == "any" or not (self.ancestors[nid] & busy):
                ready.append(nid)
        return ready

    def _start(self, running: dict, nid: str) -> None:
        msgs, self.inbox[nid] = self.inbox[nid], []
        if self.type_of(nid) == "agent":
            self.activations += 1
        running[nid] = asyncio.create_task(self.activate(nid, msgs))

    async def execute(self) -> str | None:
        inputs = [nid for nid, n in self.nodes.items() if n.get("type") == "input"]
        if not inputs:
            raise GraphError("graph needs an Input node")
        if not self.agents:
            raise GraphError("graph needs at least one Agent node")
        for nid in inputs:
            self.route(nid, NodeResult(output=self.task))

        running: dict[str, asyncio.Task] = {}
        try:
            while True:
                for nid in self._ready(running):
                    if self.activations >= self.settings.max_activations:
                        self.limit_hit = True
                        break
                    self._start(running, nid)
                if not running:
                    pending = [n for n, q in self.inbox.items() if q and not (n in self.agents and self.agents[n].busy)]
                    if pending and not self.limit_hit:
                        # Only reachable with cycles made of plain flow edges: break the tie.
                        self._start(running, pending[0])
                        continue
                    break
                # Wake on a finished activation or on a message sent mid-turn to an idle agent.
                waiter = asyncio.ensure_future(self.wake.wait())
                done, _ = await asyncio.wait([*running.values(), waiter], return_when=asyncio.FIRST_COMPLETED)
                if not waiter.done():
                    waiter.cancel()
                self.wake.clear()
                for nid in [n for n, t in running.items() if t in done]:
                    task = running.pop(nid)
                    try:
                        res = task.result()
                    except GraphError as e:
                        res = NodeResult(output=None, error=str(e), status="error")
                    if res.error:
                        self.errors.append(f"{self.label(nid)}: {res.error}")
                    self.route(nid, res)
        finally:
            for t in running.values():
                t.cancel()
            if running:
                await asyncio.gather(*running.values(), return_exceptions=True)

        if self.limit_hit:
            undelivered = sum(len(q) for q in self.inbox.values())
            self.tracer.event("limit", f"max_activations={self.settings.max_activations} reached", status="warn",
                              data={"undelivered_messages": undelivered})
        if self.outputs:
            return self.outputs[-1].content
        return self.last_agent_output


async def execute_graph(run: GraphRun) -> str | None:
    started = time.time()
    try:
        return await asyncio.wait_for(run.execute(), timeout=run.settings.timeout_s)
    except asyncio.TimeoutError:
        run.errors.append(f"run timed out after {time.time() - started:.0f}s")
        return run.outputs[-1].content if run.outputs else run.last_agent_output
