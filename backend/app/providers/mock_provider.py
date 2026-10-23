"""Deterministic offline provider for trying graphs without API keys.

Behaviour: on the first step of an activation it calls `list_dir` (if offered) to exercise the
tool path; then it answers. Simple arithmetic in the task is actually computed so datasets get
a non-trivial accuracy; anything else is echoed.
"""
from __future__ import annotations

import asyncio
import json
import random
import re

from .base import LLMParams, LLMResponse, Provider, ToolSpec, estimate_tokens

ARITH = re.compile(r"(-?\d+(?:\.\d+)?)\s*([+\-*/x×])\s*(-?\d+(?:\.\d+)?)")


def _solve(text: str) -> str | None:
    m = ARITH.search(text)
    if not m:
        return None
    a, op, b = float(m.group(1)), m.group(2), float(m.group(3))
    val = {"+": a + b, "-": a - b, "*": a * b, "x": a * b, "×": a * b, "/": a / b if b else float("nan")}[op]
    return str(int(val)) if val == int(val) else f"{val:.4g}"


class MockProvider(Provider):
    name = "mock"

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec], params: LLMParams) -> LLMResponse:
        await asyncio.sleep(random.uniform(0.15, 0.5))
        tool_names = {t.name for t in tools}
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        since_user = []
        for m in reversed(messages):
            if m["role"] == "user":
                break
            since_user.append(m)
        prompt_tokens = estimate_tokens(system + json.dumps(messages, ensure_ascii=False, default=str))

        call_id = f"mock_{random.randrange(1 << 30):x}"
        delegates = sorted(n for n in tool_names if n.startswith("ask_"))
        peers = sorted(n for n in tool_names if n.startswith("message_"))
        boards = sorted(n for n in tool_names if n.startswith("post_"))
        # Only start conversations: replying to an incoming message would ping-pong forever.
        incoming = last_user.startswith(("Message from", "Board post"))
        if not since_user and peers and not incoming:
            call = {"id": call_id, "name": peers[0], "arguments": {"text": f"Working on: {last_user[-200:]}"}}
            return LLMResponse(text="Let me tell my colleague.", tool_calls=[call], input_tokens=prompt_tokens,
                               output_tokens=14, stop_reason="tool_use", model="mock")
        if not since_user and boards and not incoming:
            call = {"id": call_id, "name": boards[0], "arguments": {"text": f"Status: started {last_user[-120:]}"}}
            return LLMResponse(text="Posting a status update.", tool_calls=[call], input_tokens=prompt_tokens,
                               output_tokens=14, stop_reason="tool_use", model="mock")
        if not since_user and delegates:
            call = {"id": call_id, "name": delegates[0], "arguments": {"task": last_user[-500:]}}
            return LLMResponse(text="Delegating.", tool_calls=[call], input_tokens=prompt_tokens,
                               output_tokens=15, stop_reason="tool_use", model="mock")
        if not since_user and "list_dir" in tool_names:
            call = {"id": call_id, "name": "list_dir", "arguments": {"path": "."}}
            return LLMResponse(text="Let me look at the workspace.", tool_calls=[call], input_tokens=prompt_tokens,
                               output_tokens=12, stop_reason="tool_use", model="mock")

        tool_results = " ".join(m["content"] for m in since_user if m["role"] == "tool")
        answer = _solve(last_user) or _solve(tool_results)
        if answer is not None:
            text = f"<answer>{answer}</answer>"
            if "APPROVED" in system:  # behave like a reviewer that accepts a computed answer
                text = f"APPROVED {text}"
        else:
            text = f"Mock response to: {last_user[-300:]}"
        return LLMResponse(text=text, tool_calls=[], input_tokens=prompt_tokens, output_tokens=estimate_tokens(text),
                           stop_reason="end_turn", model="mock",
                           reasoning=f"(mock reasoning) The request was: {last_user[-160:]}")
