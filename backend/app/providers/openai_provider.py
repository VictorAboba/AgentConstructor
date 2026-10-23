"""OpenAI Chat Completions — also serves OpenRouter, vLLM, Ollama and any OpenAI-compatible server."""
from __future__ import annotations

import json
import os

import openai

from .base import LLMParams, LLMResponse, Provider, ProviderError, ToolSpec, estimate_tokens

DEFAULT_BASE_URLS = {
    "openai": None,
    "openrouter": "https://openrouter.ai/api/v1",
    "vllm": "http://localhost:8000/v1",
    "ollama": "http://localhost:11434/v1",
}
ENV_KEYS = {"openai": "OPENAI_API_KEY", "openrouter": "OPENROUTER_API_KEY", "vllm": "VLLM_API_KEY"}


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"] or "(empty)"})
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"] or "(no output)"})
        elif role == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content") or None}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)}}
                    for tc in m["tool_calls"]
                ]
            if msg["content"] is None and "tool_calls" not in msg:
                msg["content"] = ""
            out.append(msg)
    return out


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        kind = cfg["provider"]
        self.kind = kind
        api_key = cfg.get("api_key") or os.environ.get(ENV_KEYS.get(kind, ""), "") or ("ollama" if kind == "ollama" else "EMPTY")
        headers = {}
        if kind == "openrouter":
            headers = {"X-Title": "AgentConstructor"}
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=cfg.get("base_url") or DEFAULT_BASE_URLS.get(kind),
            default_headers=headers or None,
            max_retries=4,
            timeout=600,
        )

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec], params: LLMParams) -> LLMResponse:
        oa_messages = to_openai_messages(system, messages)
        kwargs: dict = {"model": self.cfg["model"], "messages": oa_messages}
        # OpenAI's own API wants max_completion_tokens; compatible servers mostly still read max_tokens.
        if self.kind == "openai":
            kwargs["max_completion_tokens"] = params.max_tokens
        else:
            kwargs["max_tokens"] = params.max_tokens
        if params.temperature is not None:
            kwargs["temperature"] = params.temperature
        if params.effort and self.kind in ("openai", "openrouter"):
            kwargs["reasoning_effort"] = "high" if params.effort in ("xhigh", "max") else params.effort
        if tools:
            kwargs["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in tools
            ]
        if params.extra:
            kwargs["extra_body"] = params.extra
        try:
            resp = await self.client.chat.completions.create(**kwargs)
        except openai.APIError as e:
            raise ProviderError(f"{self.kind}: {e}") from e

        if not resp.choices:
            raise ProviderError(f"{self.kind}: empty response")
        choice = resp.choices[0]
        msg = choice.message
        notes: list[str] = []
        tool_calls = []
        for tc in msg.tool_calls or []:
            raw = tc.function.arguments or "{}"
            try:
                args = json.loads(raw)
                if not isinstance(args, dict):
                    args = {"value": args}
            except json.JSONDecodeError:
                args = {"_invalid_json": raw}
                notes.append(f"invalid tool-call JSON for {tc.function.name}")
            tool_calls.append({"id": tc.id or f"call_{len(tool_calls)}", "name": tc.function.name, "arguments": args})

        reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None)
        text = msg.content or ""
        usage = resp.usage
        estimated = usage is None
        if usage is not None:
            in_tok, out_tok = usage.prompt_tokens or 0, usage.completion_tokens or 0
            details = getattr(usage, "prompt_tokens_details", None)
            cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        else:
            in_tok = sum(estimate_tokens(str(m.get("content") or "")) for m in oa_messages)
            out_tok = estimate_tokens(text + json.dumps([t["arguments"] for t in tool_calls]))
            cached = 0
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cached,
            stop_reason=choice.finish_reason,
            model=resp.model,
            native=None,
            reasoning=reasoning if isinstance(reasoning, str) else None,
            estimated_usage=estimated,
            notes=notes,
        )
