"""Provider-neutral message format shared by all model backends.

History entries (plain dicts, so they serialize straight into traces):
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [ToolCall-as-dict], "native": Any, "provider": str}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}

`native` keeps the provider's own assistant payload so it can be replayed byte-for-byte
(Anthropic thinking blocks must be passed back unchanged).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema


@dataclass
class LLMParams:
    max_tokens: int = 16000
    temperature: float | None = None
    effort: str | None = None  # low|medium|high|xhigh|max (Anthropic output_config / OpenAI reasoning_effort)
    extra: dict = field(default_factory=dict)  # merged into request body as-is


@dataclass
class LLMResponse:
    text: str
    tool_calls: list[dict]  # [{"id", "name", "arguments": dict}]
    input_tokens: int
    output_tokens: int
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    stop_reason: str | None = None
    model: str | None = None  # model that actually served the request
    native: Any = None
    reasoning: str | None = None
    estimated_usage: bool = False
    notes: list[str] = field(default_factory=list)

    def assistant_message(self, provider: str) -> dict:
        return {
            "role": "assistant",
            "content": self.text,
            "tool_calls": self.tool_calls,
            "native": self.native,
            "provider": provider,
        }


class ProviderError(Exception):
    pass


class Provider:
    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg

    async def complete(self, system: str, messages: list[dict], tools: list[ToolSpec], params: LLMParams) -> LLMResponse:
        raise NotImplementedError

    def cost(self, r: LLMResponse) -> float:
        p_in = float(self.cfg.get("price_in") or 0) / 1e6
        p_out = float(self.cfg.get("price_out") or 0) / 1e6
        uncached = max(r.input_tokens - r.cached_tokens - r.cache_write_tokens, 0)
        return uncached * p_in + r.cached_tokens * p_in * 0.1 + r.cache_write_tokens * p_in * 1.25 + r.output_tokens * p_out


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
