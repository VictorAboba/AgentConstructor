from __future__ import annotations

from .base import LLMParams, LLMResponse, Provider, ProviderError, ToolSpec

PROVIDERS = {
    "openai": {"label": "OpenAI", "base_url": "", "env": "OPENAI_API_KEY"},
    "anthropic": {"label": "Anthropic", "base_url": "", "env": "ANTHROPIC_API_KEY"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY"},
    "vllm": {"label": "vLLM", "base_url": "http://localhost:8000/v1", "env": "VLLM_API_KEY"},
    "ollama": {"label": "Ollama", "base_url": "http://localhost:11434/v1", "env": ""},
    "mock": {"label": "Mock (offline)", "base_url": "", "env": ""},
}

_cache: dict[tuple, Provider] = {}


def get_provider(cfg: dict) -> Provider:
    """Providers hold HTTP clients, so they are cached per (config, credentials)."""
    key = (cfg["id"], cfg["provider"], cfg["model"], cfg.get("base_url"), cfg.get("api_key"),
           repr(sorted((cfg.get("extra") or {}).items())), cfg.get("price_in"), cfg.get("price_out"))
    if key in _cache:
        return _cache[key]
    kind = cfg["provider"]
    if kind == "anthropic":
        from .anthropic_provider import AnthropicProvider
        p: Provider = AnthropicProvider(cfg)
    elif kind in ("openai", "openrouter", "vllm", "ollama"):
        from .openai_provider import OpenAIProvider
        p = OpenAIProvider(cfg)
    elif kind == "mock":
        from .mock_provider import MockProvider
        p = MockProvider(cfg)
    else:
        raise ProviderError(f"unknown provider: {kind}")
    _cache[key] = p
    return p


__all__ = ["LLMParams", "LLMResponse", "Provider", "ProviderError", "ToolSpec", "get_provider", "PROVIDERS"]
