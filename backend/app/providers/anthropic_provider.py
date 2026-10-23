from __future__ import annotations

import os
import re

import anthropic

from .base import LLMParams, LLMResponse, Provider, ProviderError, ToolSpec

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Families where adaptive thinking is on by default, so asking for summaries changes visibility only,
# not behaviour or cost. Older models think only when enabled explicitly; we leave them untouched.
THINKING_BY_DEFAULT = re.compile(r"^claude-(fable|mythos|opus-5|sonnet-5|haiku-5)")


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []

    def push(role: str, blocks: list) -> None:
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": list(blocks)})

    for m in messages:
        role = m["role"]
        if role == "user":
            push("user", [{"type": "text", "text": m["content"] or "(empty)"}])
        elif role == "tool":
            push("user", [{
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m["content"] or "(no output)",
                "is_error": bool(m.get("is_error")),
            }])
        elif role == "assistant":
            if m.get("provider") == "anthropic" and m.get("native"):
                blocks = m["native"]
            else:
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
            push("assistant", blocks)
    return out


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        extra = cfg.get("extra") or {}
        self.use_fallbacks = bool(extra.get("fallbacks", True))
        self.use_cache = bool(extra.get("prompt_cache", True))
        self.summarize_thinking = bool(extra.get("reasoning_summary", True)) and bool(THINKING_BY_DEFAULT.match(cfg["model"]))
        self.client = anthropic.AsyncAnthropic(
            api_key=cfg.get("api_key") or os.environ.get("ANTHROPIC_API_KEY") or None,
            base_url=cfg.get("base_url") or None,
            max_retries=4,
            timeout=600,
        )

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec], params: LLMParams) -> LLMResponse:
        kwargs: dict = {
            "model": self.cfg["model"],
            "max_tokens": params.max_tokens,
            "messages": to_anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        if params.effort:
            kwargs["output_config"] = {"effort": params.effort}
        if self.use_cache:
            kwargs["cache_control"] = {"type": "ephemeral"}
        if self.summarize_thinking:
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}
        extra_body = dict(params.extra)
        if params.temperature is not None:
            # Sampling params are rejected by current models; only sent when explicitly configured.
            extra_body["temperature"] = params.temperature
        if extra_body:
            kwargs["extra_body"] = extra_body

        notes: list[str] = []
        try:
            resp = await self._create(kwargs, notes)
        except anthropic.BadRequestError as e:
            if "thinking" not in str(e).lower() or "thinking" not in kwargs:
                raise ProviderError(f"anthropic: {e}") from e
            self.summarize_thinking = False
            kwargs.pop("thinking")
            notes.append("thinking summaries rejected by this model; disabled")
            try:
                resp = await self._create(kwargs, notes)
            except anthropic.APIError as e2:
                raise ProviderError(f"anthropic: {e2}") from e2
        except anthropic.APIError as e:
            raise ProviderError(f"anthropic: {e}") from e
        except TypeError as e:
            # The SDK raises TypeError when no credential can be resolved.
            if "authentication" not in str(e).lower():
                raise
            raise ProviderError("anthropic: no API key — set it on the model or in ANTHROPIC_API_KEY") from e
        return self._parse(resp, notes)

    async def _create(self, kwargs: dict, notes: list[str]):
        if not self.use_fallbacks:
            return await self.client.messages.create(**kwargs)
        try:
            return await self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        except anthropic.BadRequestError as e:
            if "fallback" not in str(e).lower():
                raise
            # Model has no allowed fallbacks: disable for this config and retry plainly.
            self.use_fallbacks = False
            notes.append("fallbacks unsupported for this model; disabled")
            return await self.client.messages.create(**kwargs)

    def _parse(self, resp, notes: list[str]) -> LLMResponse:
        text_parts, tool_calls, reasoning = [], [], []
        native = []
        for b in resp.content:
            native.append(b.model_dump(mode="json", exclude_none=True))
            if b.type == "text":
                text_parts.append(b.text)
            elif b.type == "tool_use":
                tool_calls.append({"id": b.id, "name": b.name, "arguments": dict(b.input or {})})
            elif b.type == "thinking" and getattr(b, "thinking", ""):
                reasoning.append(b.thinking)
            elif b.type == "fallback":
                notes.append(f"fallback: {b.model_dump(mode='json')}")

        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        if resp.stop_reason == "refusal":
            details = getattr(resp, "stop_details", None)
            notes.append(f"refusal: {details.model_dump(mode='json') if details else ''}")
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            input_tokens=(u.input_tokens or 0) + cache_read + cache_write,
            output_tokens=u.output_tokens or 0,
            cached_tokens=cache_read,
            cache_write_tokens=cache_write,
            stop_reason=resp.stop_reason,
            model=resp.model,
            native=native,
            reasoning="\n".join(reasoning) or None,
            notes=notes,
        )
