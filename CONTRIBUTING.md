# Contributing

Thanks for helping! Bug reports, ideas and pull requests are all welcome. Please be kind — see the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt      # Windows: .venv\Scripts\pip
cd frontend && npm install && cd ..

cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev        # http://localhost:5173, proxies /api to :8000
```

## Checks

Run these before opening a pull request — CI runs the same:

```bash
cd backend && ../.venv/bin/python -m pytest       # uses the mock model and the local sandbox
cd frontend && npm run build                      # type-checks and builds the UI
```

Tests never need API keys or Docker. If you change engine behaviour, add a test in
`backend/tests/` that runs a small graph on the mock model (see `test_graphs.py`).

## Project layout

| Path | What lives there |
|---|---|
| `backend/app/main.py` | REST API, static UI, lifespan (seeding, MCP) |
| `backend/app/mcp_server.py` | MCP tools for Claude Code and other clients |
| `backend/app/engine/graph.py` | graph runtime: scheduler, agents, edges, generated tools, boards |
| `backend/app/engine/runner.py` | runs and experiments: sandbox setup, scoring, summaries |
| `backend/app/engine/validate.py` | static graph checks shown in the editor and enforced over MCP |
| `backend/app/engine/tracer.py` | spans and events stored for every run |
| `backend/app/providers/` | model providers (Anthropic, OpenAI-compatible, mock) |
| `backend/app/tools/` | agent tools and sandboxes (Docker / local) |
| `backend/app/templates.py` | architecture templates shown in the gallery |
| `backend/app/datasets.py` | dataset parsing, folder files and glob patterns |
| `frontend/src/pages/` | editor, run view and replay, experiments, datasets, models |
| `frontend/src/hints.ts`, `i18n.ts` | tooltip texts in English and Russian |

## Common extensions

- **A provider.** Implement `Provider.complete()` from `providers/base.py` (see `openai_provider.py`),
  register it in `providers/__init__.py` (`PROVIDERS` and `get_provider`). OpenAI-compatible
  servers usually only need a `PROVIDERS` entry with a default `base_url`.
- **An agent tool.** Add a `ToolDef` to `BUILTIN_TOOLS` in `tools/builtin.py`. Tools receive the run's
  sandbox; keep file access inside it via `sandbox.resolve()`.
- **A template.** Add a builder and an entry to `TEMPLATES` in `templates.py` with `summary` and
  `measure` in both languages. `test_graphs.py` validates and runs every template automatically.
- **An edge kind.** Touches `engine/graph.py` (semantics), `engine/validate.py`, `frontend/src/flow.tsx`
  (look and label), the editor's inspector and the replay. Open an issue first to discuss the design.

## Style

- Match the surrounding code; keep comments for the *why*.
- UI text: labels stay English; explanatory text (hints, guide) goes through `tr()` / `HINTS` with an
  English and a Russian version.
- Keep pull requests focused; describe what changed and how you checked it.
