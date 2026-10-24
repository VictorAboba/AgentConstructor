"""Starter architectures: typical multi-agent topologies to copy and compare.

Each template builds a graph for a given model id. Agent prompts are in English (they go to the
model); the summaries are shown in the UI gallery.
"""
from __future__ import annotations

SANDBOX = {"type": "docker", "image": "python:3.12-slim", "network": False, "timeout": 60}
ANSWER = "End your reply with the final answer as <answer>…</answer>."


def settings(max_activations: int = 30) -> dict:
    return {"max_activations": max_activations, "timeout_s": 900, "keep_workspace": True, "sandbox": SANDBOX}


def agent(id_: str, x: int, y: int, label: str, model_id: str, prompt: str, tools: list[str] | None = None, **extra) -> dict:
    return {"id": id_, "type": "agent", "position": {"x": x, "y": y}, "data": {
        "label": label, "model_id": model_id, "system_prompt": prompt,
        "tools": tools if tools is not None else ["shell", "read_file", "write_file", "edit_file", "list_dir", "search"],
        "max_steps": 15, "memory": "persistent", "join": "all", "include_task": True, **extra}}


def node(id_: str, type_: str, x: int, y: int, label: str) -> dict:
    return {"id": id_, "type": type_, "position": {"x": x, "y": y}, "data": {"label": label}}


def edge(id_: str, s: str, t: str, kind: str = "flow", **data) -> dict:
    return {"id": id_, "source": s, "target": t, "data": {"kind": kind, **data}}


# ---- templates ---------------------------------------------------------------------------

def single(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 120, "Task"),
        agent("solo", 240, 90, "Solver", m, f"You are a careful problem solver. Use the tools when they help. {ANSWER}",
              tools=["python", "shell", "read_file", "write_file", "list_dir", "think"]),
        node("out", "output", 540, 120, "Answer"),
    ], "edges": [edge("e1", "in", "solo"), edge("e2", "solo", "out")], "settings": settings(5)}


def pipeline(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 150, "Task"),
        agent("analyst", 220, 120, "Analyst", m,
              "Do not solve the task. Restate it precisely, list the givens, constraints and what exactly must be "
              "produced, and outline a step-by-step plan.", tools=["think"]),
        agent("solver", 500, 120, "Solver", m, f"Follow the analyst's plan and solve the task. Show your work. {ANSWER}",
              tools=["python", "think"]),
        agent("verifier", 780, 120, "Verifier", m,
              f"Independently check the solver's work against the original task: recompute key steps, test edge "
              f"cases. Fix any error you find. {ANSWER}", tools=["python", "think"]),
        node("out", "output", 1060, 150, "Answer"),
    ], "edges": [edge("e1", "in", "analyst"), edge("e2", "analyst", "solver"), edge("e3", "solver", "verifier"),
                 edge("e4", "verifier", "out")], "settings": settings(10)}


def solver_critic(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 160, "Task"),
        agent("solver", 260, 80, "Solver", m, f"Solve the task step by step. If you receive feedback, fix your solution. {ANSWER}"),
        agent("critic", 560, 160, "Critic", m,
              "Check the solver's answer. If it is correct reply APPROVED and repeat the final <answer>…</answer>; "
              "otherwise explain the mistake precisely, without giving the full solution.", tools=["think"]),
        node("out", "output", 860, 160, "Answer"),
    ], "edges": [
        edge("e1", "in", "solver"), edge("e2", "solver", "critic"),
        edge("e3", "critic", "out", "conditional", condition={"type": "contains", "value": "APPROVED"}),
        edge("e4", "critic", "solver", "feedback", condition={"type": "not_contains", "value": "APPROVED"}, max_iterations=2),
    ], "settings": settings(12)}


def self_consistency(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 200, "Task"),
        *[agent(f"a{i}", 280, 40 + 160 * i, f"Sampler {i + 1}", m, f"Solve the task independently. {ANSWER}", tools=["python"])
          for i in range(3)],
        node("vote", "vote", 580, 200, "Majority vote"),
        node("out", "output", 820, 200, "Answer"),
    ], "edges": [*[edge(f"i{i}", "in", f"a{i}") for i in range(3)], *[edge(f"v{i}", f"a{i}", "vote") for i in range(3)],
                 edge("o", "vote", "out")], "settings": settings(8)}


def mixture(m: str) -> dict:
    views = [("Formalist", "Solve it rigorously and formally, deriving every step."),
             ("Pragmatist", "Solve it the fastest practical way, computing with python where possible."),
             ("Contrarian", "Look for traps, ambiguities and the reasons the obvious answer could be wrong, then solve it.")]
    return {"nodes": [
        node("in", "input", 0, 200, "Task"),
        *[agent(f"p{i}", 260, 30 + 170 * i, name, m, f"{how} {ANSWER}", tools=["python", "think"])
          for i, (name, how) in enumerate(views)],
        agent("agg", 580, 190, "Aggregator", m,
              "You receive several candidate solutions. Compare their reasoning, identify errors, and synthesize the "
              f"single best answer — it may differ from all candidates. {ANSWER}", tools=["python", "think"]),
        node("out", "output", 880, 220, "Answer"),
    ], "edges": [*[edge(f"i{i}", "in", f"p{i}") for i in range(3)], *[edge(f"a{i}", f"p{i}", "agg") for i in range(3)],
                 edge("o", "agg", "out")], "settings": settings(8)}


def orchestrator(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 220, "Task"),
        agent("orch", 240, 190, "Orchestrator", m,
              "You coordinate specialists and never solve anything yourself, even when it looks easy: your own answers "
              "are not trusted. Always delegate before answering — at least one self-contained sub-task via the ask_* "
              "tools, and have the Reviewer check the draft. Then combine the results. "
              f"{ANSWER}", tools=["think"]),
        agent("research", 580, 20, "Researcher", m, "Answer the sub-task precisely and concisely; state assumptions.",
              tools=["think"]),
        agent("coder", 580, 210, "Coder", m, "Solve the sub-task by writing and running code in the workspace. Report results, not just code.",
              tools=["python", "shell", "read_file", "write_file", "edit_file", "list_dir"]),
        agent("review", 580, 400, "Reviewer", m, "Critically review the work you are given: find errors and say how confident you are.",
              tools=["python", "think"]),
        node("out", "output", 240, 420, "Answer"),
    ], "edges": [
        edge("e1", "in", "orch"), edge("d1", "orch", "research", "delegate", label="Facts, definitions, reasoning."),
        edge("d2", "orch", "coder", "delegate", label="Anything that can be computed or needs files."),
        edge("d3", "orch", "review", "delegate", label="Double-check a draft answer."),
        edge("o", "orch", "out"),
    ], "settings": settings(25)}


def hierarchy(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 280, "Task"),
        agent("dir", 220, 250, "Director", m,
              "You lead two teams and never solve anything yourself, even when it looks easy. Always give an assignment "
              "to BOTH the research lead and the engineering lead with the ask_* tools, reconcile their reports and "
              f"decide. {ANSWER}", tools=["think"]),
        agent("rlead", 540, 100, "Research lead", m,
              "You manage two analysts and do not answer on your own. Break your assignment into questions, delegate "
              "them to both analysts with ask_* tools, and send back a concise report with conclusions and confidence.",
              tools=["think"]),
        agent("elead", 540, 420, "Engineering lead", m,
              "You manage a coder and a tester and do not compute anything yourself. Always have the coder "
              "implement/compute and the tester verify (ask_* tools), then send back a concise report with verified "
              "results.", tools=["think"]),
        agent("fact", 860, 20, "Analyst A", m, "Answer the question you are given carefully.", tools=["think"]),
        agent("calc", 860, 190, "Analyst B", m, "Answer the question you are given, computing with python where possible.", tools=["python"]),
        agent("coder", 860, 340, "Coder", m, "Implement or compute what is asked in the workspace and report the result.",
              tools=["python", "shell", "read_file", "write_file", "edit_file", "list_dir"]),
        agent("tester", 860, 510, "Tester", m, "Verify the given result independently (tests, recomputation) and report pass/fail with evidence.",
              tools=["python", "shell", "read_file", "list_dir"]),
        node("out", "output", 220, 480, "Answer"),
    ], "edges": [
        edge("e1", "in", "dir"), edge("d1", "dir", "rlead", "delegate"), edge("d2", "dir", "elead", "delegate"),
        edge("d3", "rlead", "fact", "delegate"), edge("d4", "rlead", "calc", "delegate"),
        edge("d5", "elead", "coder", "delegate"), edge("d6", "elead", "tester", "delegate"),
        edge("o", "dir", "out"),
    ], "settings": {**settings(30), "max_delegate_depth": 3}}


def router(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 200, "Task"),
        agent("triage", 240, 170, "Triage", m,
              "Do not solve the task. Decide which specialist fits best and hand off with the matching handoff_to_* tool, "
              "passing the task and any hints.", tools=[]),
        agent("math", 560, 20, "Math expert", m, f"Solve mathematical tasks rigorously; compute with python. {ANSWER}", tools=["python"]),
        agent("code", 560, 190, "Code expert", m, f"Solve programming tasks by writing and running code. {ANSWER}",
              tools=["python", "shell", "read_file", "write_file", "edit_file", "list_dir"]),
        agent("general", 560, 360, "Generalist", m, f"Answer general-knowledge and reasoning tasks carefully. {ANSWER}", tools=["think"]),
        node("out", "output", 880, 200, "Answer"),
    ], "edges": [
        edge("e1", "in", "triage"),
        edge("h1", "triage", "math", "handoff", label="Arithmetic, algebra, counting, probability."),
        edge("h2", "triage", "code", "handoff", label="Writing, fixing or running programs; data processing."),
        edge("h3", "triage", "general", "handoff", label="Everything else."),
        edge("o1", "math", "out"), edge("o2", "code", "out"), edge("o3", "general", "out"),
    ], "settings": settings(8)}


def debate(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 200, "Task"),
        agent("pro", 260, 60, "Debater A", m,
              "Solve the task. Then send your answer and key argument to your opponent with message_*. When the opponent "
              "writes, either defend your answer with a concrete argument or concede if they are right. Send at most two "
              f"messages in total. Finish with your current position. {ANSWER}", tools=["python", "think"]),
        agent("con", 260, 340, "Debater B", m,
              "Solve the task independently. When the other debater writes, look for flaws in their argument and reply "
              "with message_*; concede only to a convincing argument. Send at most two messages in total. Finish with "
              f"your current position. {ANSWER}", tools=["python", "think"]),
        agent("judge", 600, 200, "Judge", m,
              f"Two debaters give their final positions. Weigh the arguments, not the confidence, and give the verdict. {ANSWER}",
              tools=["think"]),
        node("out", "output", 900, 230, "Answer"),
    ], "edges": [
        edge("e1", "in", "pro"), edge("e2", "in", "con"),
        edge("m", "pro", "con", "message", bidirectional=True, label="Argue about the answer."),
        edge("j1", "pro", "judge"), edge("j2", "con", "judge"), edge("o", "judge", "out"),
    ], "settings": settings(16)}


def swarm(m: str) -> dict:
    ids = ["s1", "s2", "s3", "s4"]
    pos = {"s1": (300, 40), "s2": (620, 40), "s3": (300, 360), "s4": (620, 360)}
    prompt = ("You are one of four equal peers in a swarm; nobody is in charge. Work on the task and, before giving "
              "your final answer, send your result (one short message) to at least one peer with the message_* tools. "
              "Take peers' messages into account; reply only if you disagree. "
              f"{ANSWER}")
    nodes = [node("in", "input", 0, 220, "Task"),
             *[agent(i, *pos[i], f"Peer {k + 1}", m, prompt, tools=["python", "think"]) for k, i in enumerate(ids)],
             node("vote", "vote", 940, 220, "Consensus vote"), node("out", "output", 1160, 220, "Answer")]
    mesh = [edge(f"m_{a}_{b}", a, b, "message", bidirectional=True) for k, a in enumerate(ids) for b in ids[k + 1:]]
    return {"nodes": nodes, "edges": [*[edge(f"i_{i}", "in", i) for i in ids], *mesh,
                                      *[edge(f"v_{i}", i, "vote") for i in ids], edge("o", "vote", "out")],
            "settings": settings(24)}


def blackboard(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 230, "Task"),
        agent("analyst", 260, 40, "Analyst", m, "Work out the reasoning for the task and post your key findings to the board.",
              tools=["think"]),
        agent("calc", 260, 230, "Calculator", m, "Compute every quantity the task needs with python and post the numbers to the board.",
              tools=["python"]),
        agent("skeptic", 260, 420, "Skeptic", m,
              "You receive the board's posts. Post an objection only when a claim is wrong or unsupported, citing the "
              "post; otherwise stay silent.", tools=["python", "think"]),
        node("board", "board", 600, 230, "Blackboard"),
        agent("synth", 900, 200, "Synthesizer", m,
              f"Read everything on the board (read_* tool) and the specialists' reports, resolve disagreements and give the answer. {ANSWER}",
              tools=["think"]),
        node("out", "output", 1180, 230, "Answer"),
    ], "edges": [
        edge("i1", "in", "analyst"), edge("i2", "in", "calc"), edge("i3", "in", "skeptic"),
        edge("p1", "analyst", "board", "message"), edge("p2", "calc", "board", "message"),
        edge("p3", "skeptic", "board", "message", bidirectional=True),
        edge("s1", "synth", "board", "subscribe"),
        edge("r1", "analyst", "synth"), edge("r2", "calc", "synth"), edge("r3", "skeptic", "synth"),
        edge("o", "synth", "out"),
    ], "settings": settings(24)}


def team_chat(m: str) -> dict:
    return {"nodes": [
        node("in", "input", 0, 200, "Task"),
        agent("lead", 240, 170, "Lead", m, "Coordinate the team. Ask the Researcher for what you need by message, read the "
              f"board, and give the final answer. {ANSWER}", tools=["think"]),
        agent("research", 560, 40, "Researcher", m, "Answer the Lead's questions precisely. Post noteworthy findings to the board.",
              tools=["python", "think"]),
        agent("coder", 560, 330, "Coder", m, "When something can be computed, compute it with python and post the result to the board.",
              tools=["python", "read_file", "write_file", "list_dir"]),
        node("board", "board", 900, 190, "Team board"),
        node("out", "output", 520, 520, "Answer"),
    ], "edges": [
        edge("e1", "in", "lead"), edge("e2", "in", "coder"),
        edge("m1", "lead", "research", "message", bidirectional=True),
        edge("p1", "research", "board", "message"), edge("p2", "coder", "board", "message"),
        edge("s1", "lead", "board", "subscribe"), edge("o1", "lead", "out"),
    ], "settings": settings(20)}


# summary / measure: {"en": ..., "ru": ...}; the UI shows the viewer's language.
TEMPLATES: list[dict] = [
    {"id": "single", "name": "Single agent (baseline)", "category": "Baseline", "build": single,
     "summary": {"en": "A single agent with tools. The baseline: compare every multi-agent scheme with it on the same dataset.",
                 "ru": "Один агент с инструментами. Точка отсчёта: любую мультиагентную схему стоит сравнивать с ним на том же датасете."},
     "measure": {"en": "Accuracy and cost per correct answer — the bar the other schemes have to beat.",
                 "ru": "Точность и стоимость правильного ответа — планка, которую должны превзойти остальные схемы."}},
    {"id": "pipeline", "name": "Pipeline", "category": "Sequential", "build": pipeline,
     "summary": {"en": "Pipeline: an analyst restates the task and plans → a solver → a verifier. Each stage sees only the previous stage's output.",
                 "ru": "Конвейер: аналитик формулирует задачу и план → решатель → верификатор. Каждый этап видит только выход предыдущего."},
     "measure": {"en": "Which stage adds value: drop the analyst or the verifier and compare accuracy and tokens.",
                 "ru": "Какой этап даёт прирост: уберите аналитика или верификатора и сравните точность и токены."}},
    {"id": "solver_critic", "name": "Solver ⇄ Critic", "category": "Sequential", "build": solver_critic,
     "summary": {"en": "Reflection: a critic checks the solution and sends it back for rework (feedback edge) until it writes APPROVED.",
                 "ru": "Рефлексия: критик проверяет решение и возвращает его на доработку (feedback-связь), пока не напишет APPROVED."},
     "measure": {"en": "How many iterations are really needed, and how often the critic misses errors or breaks correct answers.",
                 "ru": "Сколько итераций реально нужно и как часто критик пропускает ошибки или «ломает» верные ответы."}},
    {"id": "self_consistency", "name": "Self-consistency ×3", "category": "Ensemble", "build": self_consistency,
     "summary": {"en": "Three independent solutions → majority vote without an LLM.",
                 "ru": "Три независимых решения → голосование большинством без LLM."},
     "measure": {"en": "Accuracy gain versus 3× cost; spread of answers between the samplers.",
                 "ru": "Прирост точности против ×3 к стоимости; разброс ответов между семплерами."}},
    {"id": "mixture", "name": "Mixture of agents", "category": "Ensemble", "build": mixture,
     "summary": {"en": "Three agents with different strategies solve in parallel; an LLM aggregator compares their reasoning and synthesizes the answer.",
                 "ru": "Три агента с разными стратегиями решают параллельно, агрегатор (LLM) сравнивает рассуждения и синтезирует ответ."},
     "measure": {"en": "Compare with Self-consistency: is the LLM aggregator worth its cost over a plain vote?",
                 "ru": "Сравните с Self-consistency: оправдывает ли LLM-агрегатор свою стоимость по сравнению с голосованием."}},
    {"id": "orchestrator", "name": "Orchestrator → workers", "category": "Centralized", "build": orchestrator,
     "summary": {"en": "Centralized orchestration: the orchestrator plans and delegates sub-tasks to specialists (delegate) and solves nothing itself.",
                 "ru": "Централизованная оркестрация: оркестратор планирует и делегирует подзадачи специалистам (delegate), сам ничего не решает."},
     "measure": {"en": "Delegations per task and the share of tokens spent on coordination versus work.",
                 "ru": "Сколько делегирований на задачу, какая доля токенов уходит на координацию, а какая — на работу."}},
    {"id": "hierarchy", "name": "Hierarchy (2 levels)", "category": "Centralized", "build": hierarchy,
     "summary": {"en": "Hierarchy: a director → two team leads → two workers each. Delegation on two levels.",
                 "ru": "Иерархия: директор → два тимлида → по два исполнителя. Делегирование на двух уровнях."},
     "measure": {"en": "The price of depth: latency and tokens versus a flat orchestrator on the same tasks.",
                 "ru": "Цена глубины: латентность и токены против плоского оркестратора на тех же задачах."}},
    {"id": "router", "name": "Router (handoff)", "category": "Centralized", "build": router,
     "summary": {"en": "Router: a dispatcher picks a specialist and hands control over (handoff); only the chosen one answers.",
                 "ru": "Маршрутизатор: агент-диспетчер выбирает специалиста и передаёт ему управление (handoff); отвечает только выбранный."},
     "measure": {"en": "Routing accuracy (the choice is visible in the trace) and savings versus running every specialist.",
                 "ru": "Точность маршрутизации (кого выбрал диспетчер — видно в трейсе) и экономия против «всех специалистов сразу»."}},
    {"id": "debate", "name": "Debate + judge", "category": "Decentralized", "build": debate,
     "summary": {"en": "Debate: two agents solve independently and argue over a two-way message edge; a judge gives the verdict.",
                 "ru": "Дебаты: два агента решают независимо и спорят через двустороннюю связь сообщений, судья выносит вердикт."},
     "measure": {"en": "How often a debate fixes a wrong answer and how often it talks an agent out of a right one.",
                 "ru": "Как часто дебаты исправляют неверный ответ и как часто убеждают сдать верный."}},
    {"id": "swarm", "name": "Swarm (messages only)", "category": "Decentralized", "build": swarm,
     "summary": {"en": "Swarm: four equal agents in a full mesh of message edges, no leader. The result is a vote.",
                 "ru": "Рой: четыре равноправных агента, полносвязная сеть только из связей сообщений, без лидера. Итог — голосование."},
     "measure": {"en": "Message volume (message events) versus accuracy gain; do the agents converge on one answer?",
                 "ru": "Объём переписки (число message-событий) против прироста точности; сходятся ли агенты к одному ответу."}},
    {"id": "blackboard", "name": "Blackboard", "category": "Shared memory", "build": blackboard,
     "summary": {"en": "Blackboard: specialists post findings to a shared board, a subscribed skeptic challenges mistakes, a synthesizer reads everything and answers.",
                 "ru": "Доска: специалисты публикуют находки на общую доску, скептик подписан и оспаривает ошибки, синтезатор читает всё и отвечает."},
     "measure": {"en": "Posts and objections per task; do the skeptic's objections help or only burn tokens?",
                 "ru": "Сколько постов и возражений на задачу; помогают ли возражения скептика или только тратят токены."}},
    {"id": "team_chat", "name": "Team chat + board", "category": "Shared memory", "build": team_chat,
     "summary": {"en": "Mixed scheme: the lead messages a researcher directly and subscribes to a board where a coder posts calculations.",
                 "ru": "Смешанная схема: лид переписывается с исследователем напрямую и подписан на доску, куда кодер публикует расчёты."},
     "measure": {"en": "Which channel is used more — direct messages or the board — and how it affects the lead's activations.",
                 "ru": "Что используется чаще — прямые сообщения или доска, и как это влияет на число активаций лида."}},
]
BY_ID: dict[str, dict] = {t["id"]: t for t in TEMPLATES}


def build(template_id: str, model_id: str) -> dict:
    return BY_ID[template_id]["build"](model_id)


def catalog() -> list[dict]:
    """Template metadata plus a light preview (positions, types, edge kinds) for the gallery."""
    out = []
    for t in TEMPLATES:
        g = t["build"]("")
        out.append({
            "id": t["id"], "name": t["name"], "category": t["category"], "summary": t["summary"]["en"], "measure": t["measure"]["en"],
            "summary_ru": t["summary"]["ru"], "measure_ru": t["measure"]["ru"],
            "agents": sum(n["type"] == "agent" for n in g["nodes"]),
            "preview": {
                "nodes": [{"id": n["id"], "type": n["type"], "x": n["position"]["x"], "y": n["position"]["y"],
                           "label": n["data"].get("label")} for n in g["nodes"]],
                "edges": [{"source": e["source"], "target": e["target"], "kind": e["data"]["kind"],
                           "bidirectional": bool(e["data"].get("bidirectional"))} for e in g["edges"]],
            },
        })
    return out

