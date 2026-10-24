# AgentConstructor

[![CI](https://github.com/VictorAboba/AgentConstructor/actions/workflows/ci.yml/badge.svg)](https://github.com/VictorAboba/AgentConstructor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)

**A no-code lab for building multi-agent LLM systems as graphs and measuring how they behave.**
Wire agents together in a visual editor, run the graph on a dataset of tasks with reference
answers, and compare architectures by accuracy, latency, tokens, cost and full interaction traces.

[Русская версия](README.ru.md)

![Graph editor with the Blackboard template](docs/img/editor.png)

- **Visual graph editor** — agents, votes, message boards; seven connection kinds from plain dataflow
  to delegation, direct messages and board subscriptions.
- **12 architecture templates** — pipeline, solver ⇄ critic, self-consistency, mixture of agents,
  orchestrator, hierarchy, router, debate, swarm, blackboard and more, ready to run.
- **Experiments** — run a graph over a dataset with concurrency and repeats; accuracy, mean / median /
  p95 latency, tokens, cost per correct answer, per-agent breakdown; side-by-side comparison.
- **Traces** — every model call, tool call, message and thought, with the system prompt in effect;
  a step-by-step replay animates the run on the graph.
- **Sandboxes** — agents get `shell`, `python` and file tools inside a per-run workspace, isolated in
  Docker (no network by default) or run locally.
- **Providers** — OpenAI, Anthropic, OpenRouter, vLLM, Ollama, plus an offline mock model.
- **MCP server** — Claude Code and other MCP clients can create models, graphs and datasets and run
  experiments for you.

```
backend/   FastAPI + SQLite: model providers, sandboxes, graph engine, tracing, experiments, MCP
frontend/  React + React Flow: graph editor, traces, replay, experiments, comparison
data/      created on first start: SQLite database and run workspaces (workspaces/<run_id>)
```

## Quick start

Requirements: Python 3.11+, Node.js 18+, and Docker if you want isolated sandboxes (recommended).

```bash
./start.sh           # macOS / Linux
```

```powershell
./start.ps1          # Windows
```

The script creates a virtualenv, builds the UI on first run and serves everything on
http://localhost:8000. A fresh install contains a mock model (works without keys), a small
arithmetic dataset and one example graph per architecture template.

Add a real model on the **Models** page (or set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`OPENROUTER_API_KEY` in the environment), pick a template with **New**, press **▶ Run**, then
**Evaluate on dataset**. The **Guide** button (bottom left) walks through the same steps; the
**EN / RU** switch below it changes the language of hints and the guide.

| Step-by-step replay | Architecture templates | Experiment comparison |
|---|---|---|
| ![Replay](docs/img/replay.png) | ![Templates](docs/img/gallery.png) | ![Compare](docs/img/compare.png) |

## Concepts

**Nodes**

| Type | What it does |
|---|---|
| Input | emits the task text when a run starts |
| Agent | an LLM with a tool loop: model, system prompt, tools, step limit, effort, memory (persistent / fresh), join (all / any). A turn ends when the model replies without calling tools — that reply is the agent's output |
| Vote | no LLM: majority vote over incoming answers (self-consistency, ensembles) |
| Board | a message board: agents post to it, subscribers receive the posts |
| Output | the last answer it receives is the run's result, the one that is scored |

**Connections**

| Kind | Semantics |
|---|---|
| Flow | the source's output is delivered to the target |
| Conditional | delivered if the output matches a condition (contains / not contains / regex) |
| Feedback | a back-edge that may form loops, limited by `max_iterations` |
| Handoff | the agent gets `handoff_to_<target>`; control moves only if the agent calls it |
| Delegate | the agent gets `ask_<target>`: the target runs as a sub-agent and its answer comes back as the tool result |
| Message | the agent gets `message_<target>` to write to another agent at any time without ending its turn. "Two-way" gives the target the reverse tool. A message edge to a board gives `post_<board>` |
| Subscribe | agent ↔ board: the agent receives new posts of the board — from everyone or only from chosen authors (`authors`); it can read the rest with `read_<board>` |

The scheduler is dataflow: an agent with `join=all` waits for all its ancestors and handles all
incoming messages at once; parallel branches run concurrently. Direct messages and board posts are
asynchronous: a busy recipient gets them before its next model call (an `inject` event in the
trace), an idle one is activated. The node inspector lists the tools an agent gets from its
connections ("From connections"), and the editor validates the graph as you edit.

**Agent tools** (all run in the run's sandbox): `shell`, `python`, `read_file`, `write_file`,
`edit_file`, `list_dir`, `search` (regex over files), `think` (for models without built-in reasoning).

**Reasoning in traces.** Thoughts are recorded automatically as `thought` events — both `think`
calls and the model's own reasoning. For Claude 5.x the server asks for reasoning summaries
(`thinking.display = "summarized"`); this does not change behaviour or cost. For OpenAI-compatible
servers `reasoning_content` / `reasoning` is kept when the server returns it (vLLM, DeepSeek,
OpenRouter).

**Sandboxes.** Every run has its own folder `data/workspaces/<run_id>`, shared by the run's agents.
- `docker` (default): a `python:3.12-slim` container with the folder mounted at `/workspace`,
  network off, CPU / memory / process limits. If Docker is not running the run fails with an error —
  there is no silent fallback to the host.
- `local`: a host process with `cwd` = workspace and secrets stripped from the environment. File
  tools cannot leave the workspace, but shell commands are **not isolated**.

**Providers:** OpenAI, Anthropic, OpenRouter, vLLM, Ollama (the last three through the
OpenAI-compatible API) and Mock. Keys go into the model settings or the environment variables above.
For Anthropic, prompt caching and the server-side refusal fallback (`fallbacks: "default"`) are on by
default; if another model served a request, the trace says so ("served by"). Turn the fallback off
for strict model comparisons. vLLM serves on port 8000 by default, like AgentConstructor —
start one of them on another port (`PORT=8080 ./start.sh` or `vllm serve … --port 8001`).

## Architecture templates

**New** in the editor opens a gallery of typical architectures; every agent gets the model you pick
(change it per agent later).

| Group | Template | What it is |
|---|---|---|
| Baseline | Single agent | one agent with tools — the reference point for every other scheme |
| Sequential | Pipeline | analyst → solver → verifier along `flow` edges |
| | Solver ⇄ Critic | a critic sends the solution back (`feedback`) until it is APPROVED |
| Ensemble | Self-consistency ×3 | three independent solutions → vote without an LLM |
| | Mixture of agents | three agents with different strategies → an LLM aggregator |
| Centralized | Orchestrator → workers | a coordinator only hands out sub-tasks (`delegate`) and assembles the answer |
| | Hierarchy (2 levels) | director → two team leads → workers (`delegate`, depth 3) |
| | Router (handoff) | a dispatcher hands control to one specialist (`handoff`) |
| Decentralized | Debate + judge | two agents argue over a two-way `message` edge, a judge decides |
| | Swarm | four equal agents, only two-way `message` edges, the result is a vote |
| Shared memory | Blackboard | specialists post findings to a board, a subscribed skeptic (`subscribe`) challenges mistakes, a synthesizer answers |
| | Team chat + board | a lead messages a researcher directly and subscribes to a board where a coder posts calculations |

Each card says what is worth measuring on it. Over MCP: `list_templates` and
`create_graph_from_template`; over REST: `GET /api/templates` and `POST /api/graphs/from-template`.

## Datasets

JSONL, a JSON array or CSV. Task field: `task | question | input | prompt | problem | query`;
answer: `answer | expected | output | target | solution | reference | label`. Optional extras:

```json
{"task": "Fix calc.py so the tests pass. Reply DONE.", "answer": "DONE",
 "files": {"calc.py": "def add(a, b):\n    return a - b\n"}, "setup": "pip install -q pytest"}
```

`files` are written into the sandbox before the run; `setup` runs there too. Instead of inline
content, `files` can point to a folder on this machine, copied into the sandbox when each run starts:

```json
{"task": "…", "answer": "DONE", "files": "/bench/repo1"}
{"task": "…", "answer": "DONE", "files": "/bench/repo1", "files_glob": "**/*.py; !**/__pycache__/**"}
{"task": "…", "answer": "DONE", "files": {"dir": "/bench/repo1", "glob": ["src/**", "*.toml"]}}
```

- **Patterns** (`files_glob` or `glob`; several separated by `;` or as a list): without `/` — by file
  name at any depth (`*.py`); with `/` — a path from the folder root (`src/**/*.ts`, `**` = any
  directories); `re:<regex>` — a regex over the relative path; a leading `!` excludes. No pattern
  copies the whole folder.
- **Relative paths** resolve against the dataset file's folder (MCP import) or the project root.
  Task fields can be substituted: `tasks/{id}`.
- **A folder for the whole dataset:** fill "Files folder" and "Glob" when uploading on the Datasets
  page (`files_dir` / `files_glob` over MCP). They apply to tasks without their own `files`.
- In CSV, put the path in a `files` column and the pattern in `files_glob`.
- Folders and patterns are checked on upload (missing folder or no matching files fails the upload).
  Limit: 5000 files / 200 MB per task. The sandbox span of the trace records the copied files, their
  size and a content hash, so a folder that changed between experiments is easy to spot.

**Scoring:** `auto` (numbers compared numerically, otherwise exact match / containment), `exact`,
`contains`, `numeric`, `regex`, `llm_judge` (a chosen model compares with the reference; its cost is
counted separately), `none`. The answer is taken from the last `<answer>…</answer>` or a
`Final answer: …` line.

## What is measured

Per run: duration, input / output / cached tokens, cost, LLM calls, tool calls and agent
activations, plus the same per node. The trace is a span tree `run → sandbox / node → llm / tool /
delegate` with `message`, `vote` and `limit` events. An LLM span shows what the model received since
its previous step, its reply, tool calls and reasoning; agent activations and LLM steps show the
system prompt in effect and the tools offered.

**Step-by-step** (a tab on the run page) replays the run on the graph: activations starting and
ending, model replies, tool calls, messages along edges. Nodes are coloured by their state at the
current step and show accumulated tokens and cost. Keys: `←` `→`, `Space` (autoplay, also in real
time), `Home` / `End`; hover a node or edge to inspect it, click to pin a node.

Per experiment: accuracy, mean / median / p95 latency, tokens and cost per task, cost per correct
answer, errors, per-agent contribution. `repeats` measure variance. **Compare** puts experiments
side by side, overall and per task. Exports: CSV / JSONL per experiment, JSON with the full trace
per run.

## MCP: drive it from Claude Code and other clients

The server exposes MCP over streamable HTTP at `http://localhost:8000/mcp`. The repository ships a
`.mcp.json`, so Claude Code started in the project folder offers to connect. Elsewhere:

```bash
claude mcp add --transport http agentconstructor http://localhost:8000/mcp
```

Tools: `overview` (graph and dataset schema — start here), `list_models`, `add_model`, `test_model`,
`list_graphs`, `get_graph`, `list_templates`, `create_graph_from_template`, `save_graph` (validated;
an invalid graph is not saved), `delete_graph`, `list_datasets`, `get_dataset`, `create_dataset`,
`add_dataset_items`, `import_dataset_file` (local JSONL / JSON / CSV), `delete_dataset`, `run_task`,
`get_run` (trace as a timeline), `start_experiment`, `get_experiment` (can wait for completion),
`list_experiments`, `compare_experiments`, `cancel`. Model API keys are never returned over MCP.

## REST API

Everything the UI does is available over REST (Swagger at `/docs`): `/api/models`, `/api/graphs`,
`/api/graphs/validate`, `/api/templates`, `/api/graphs/from-template`, `/api/datasets`, `/api/runs`,
`/api/experiments`, `/api/runs/{id}/export`, `/api/experiments/{id}/export?format=csv|jsonl`.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend && ../.venv/bin/python -m uvicorn app.main:app --reload --port 8000   # API + built UI
cd frontend && npm install && npm run dev                                         # UI with hot reload on :5173
cd backend && ../.venv/bin/python -m pytest                                       # tests (mock model, no keys or Docker)
```

`AGENTCONSTRUCTOR_DATA` moves the database and workspaces to another folder. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the project layout and how to add a provider, a tool or a
template.

## Security

AgentConstructor is a local research tool: the server binds to `127.0.0.1`, has **no
authentication**, stores API keys in the local SQLite database and lets agents run code. Do not
expose it to a network you do not trust, and prefer the Docker sandbox. See [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
