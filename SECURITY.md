# Security

## Threat model

AgentConstructor is meant to run on your own machine for research. Keep in mind:

- **No authentication.** The server listens on `127.0.0.1` only. Anyone who can reach the port can
  read traces, change models and run agents. Do not bind it to `0.0.0.0` or put it behind a public
  proxy.
- **API keys are stored in plain text** in the local SQLite database (`data/agentconstructor.db`).
  They are masked in the UI and never returned over MCP. Do not share the `data/` folder.
- **Agents execute code.** With the `docker` sandbox commands run in a throwaway container with no
  network by default and resource limits. With the `local` sandbox, file tools are confined to the
  run folder but **shell and Python commands run on your machine with your permissions**. Use
  `local` only with models and tasks you trust.
- **Dataset folders are copied from your machine** into the sandbox, where agents can read them.
  Don't point `files` at folders with secrets.
- **Prompt injection.** Tasks, files and tool output reach the model; an agent can be talked into
  misusing its tools. The sandbox is the boundary — keep the network off unless a task needs it.

## Reporting a vulnerability

Please report security issues privately through GitHub:
**Security → Report a vulnerability** on the repository page (private vulnerability reporting).
Include steps to reproduce and the impact you see. Please do not open a public issue for
vulnerabilities.
