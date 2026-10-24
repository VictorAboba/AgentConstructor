# Changelog

## 0.1.0 — first public release

- Visual graph editor with Input, Agent, Vote, Board and Output nodes and seven connection kinds:
  flow, conditional, feedback, handoff, delegate, message (one- or two-way) and subscribe (with an
  optional author filter).
- 12 architecture templates with an in-editor gallery.
- Runs and experiments on datasets: accuracy, latency percentiles, tokens, cost, per-agent stats,
  repeats, comparison, CSV / JSONL / JSON export.
- Traces with system prompts and reasoning, step-by-step replay on the graph.
- Docker and local sandboxes with shell, Python and file tools; dataset files inline or from a host
  folder with glob / regex filters.
- Providers: OpenAI, Anthropic, OpenRouter, vLLM, Ollama, offline mock.
- MCP server for Claude Code and other clients.
- English and Russian hints and guide.
