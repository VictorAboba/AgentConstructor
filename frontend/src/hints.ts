import { LANG } from './i18n'

/** Short explanations shown in "?" tooltips across the UI. */
const EN = {
  connectAs: 'Kind of connection a new arrow gets. Drag from the right handle of a node to the left handle of another. You can change the kind later by clicking the arrow.',
  run: 'One run of the graph on a task you type in. Handy for debugging: nodes light up as they work, then you can open the trace.',
  evaluate: 'Run the graph on a whole dataset and measure accuracy, time, tokens and cost. Results appear under Experiments.',
  palette: 'Input — where the task comes from. Agent — an LLM with tools. Vote — majority vote over answers. Board — a message board for a group of agents. Output — the final answer, the one that is scored.',

  model: 'Which LLM drives the agent. Models are added on the Models page; mock needs no keys and is good for checking a graph.',
  systemPrompt: 'The agent\'s role and rules. Context is appended automatically: the agent\'s name, the shared workspace and the tools that come from connections (can be turned off below).',
  tools: 'What the agent can do in the sandbox. A turn ends when the model replies with text and no tool calls — that text is its output. think helps models without built-in reasoning: thoughts go to the trace.',
  generatedTools: 'Tools the agent gets automatically from graph connections: handoff/delegate/message to other agents, post/read for boards. Nothing to configure — change the connections instead.',
  maxSteps: 'How many model calls an agent may make in one activation (each round of tool calls is another step). Guards against endless loops.',
  maxTokens: 'Token limit for one model reply. Empty — 16000.',
  effort: 'How deeply the model thinks (Anthropic effort / OpenAI reasoning_effort). Lower is faster and cheaper, higher is more accurate on hard tasks.',
  temperature: 'Sampling randomness. Recent Anthropic models reject this parameter — leave it empty if unsure.',
  memory: 'persistent — the agent remembers its whole conversation across activations (important for solver ⇄ critic loops). fresh — every activation starts from a clean slate.',
  join: 'all — the agent waits until every upstream node is done and receives all messages at once. any — it runs on each incoming message separately.',
  includeTask: 'Put the original task into the agent\'s first message. Turn off if the agent should see only what others pass to it.',
  autoContext: 'Append service context about the role and tools to the system prompt. Turn off for full control over the prompt in experiments.',

  edgeKind: 'flow — pass the output on. conditional — pass it if a condition holds. feedback — a back-edge for loops. handoff — the agent decides to transfer control. delegate — the agent calls another one as a sub-agent. message — the agent can write to another at any time without ending its turn. subscribe — the agent receives a board\'s posts: from everyone or from chosen authors.',
  bidirectional: 'Two-way connection: both agents get a tool to write to each other. With a board, the agent both posts to it and receives its posts.',
  subscribe: 'Board subscription: each new post arrives as a message. If the agent is working, before its next model call; if it is idle, it gets activated.',
  filesDir: 'A folder on this machine copied into the sandbox of every task before it runs — for tasks without their own files field. Relative paths start at the project root. Task fields can be substituted: tasks/{id}. The folder is copied on every run; the trace records the file list and a content hash.',
  filesGlob: 'Which files of the folder to take. Several patterns separated by ";". Without "/" — by file name at any depth (*.py); with "/" — a path from the folder root (src/**/*.ts); "re:…" — a regex over the relative path; a leading "!" excludes (!**/node_modules/**). Empty — the whole folder.',
  subscribeAuthors: 'Whose posts are delivered to the subscriber. "everyone" — all posts; tick authors to receive only theirs. The agent can still read the other posts with read_<board>.',
  board: 'A board is a shared channel for a group. Agents with a Message connection post to it, agents with a Subscribe connection receive its posts. Good for broadcast coordination without a fixed who-talks-to-whom scheme.',
  condition: 'Checked against the source\'s output text. contains / not contains — case-insensitive; regex — a regular expression.',
  maxIterations: 'How many times a message may go through this back-edge in one run. After the limit the loop stops.',
  toolDescription: 'Tells the agent when to call this handoff/delegate/message tool. Goes into the tool description.',

  sandbox: 'Where agents\' commands run. Docker — an isolated container without network (recommended). Local — directly on your machine in the run folder.',
  network: 'Let the container reach the internet (pip install, downloads). Off by default.',
  setup: 'A command run in the sandbox before each task — for example, installing dependencies.',
  maxActivations: 'Total limit of agent activations per run, delegation included. Guards against looping graphs.',
  runTimeout: 'Maximum duration of one run. After it, the last answer received is used.',

  scorer: 'How the answer is compared with the reference. auto fits most cases: numbers are compared numerically, text exactly or by containment. The answer is taken from <answer>…</answer>.',
  concurrency: 'How many dataset tasks run at the same time. More is faster but hits provider rate limits sooner.',
  repeats: 'How many times to run each task. Several repeats show the spread of results for non-deterministic agents.',

  price: 'Price per million tokens — used to compute run cost. Check the provider\'s pricing page.',
  fallback: 'If the model refuses for safety reasons, Anthropic can resend the request to another model. Turn off for clean model comparisons.',
  promptCache: 'Caching of the repeated start of the conversation. Agent loops resend the whole history every step — the cache cuts cost noticeably.',

  replay: 'Step-by-step replay of a run. ← → — step back/forward, Space — autoplay, Home/End — start/end. Hover a node or an arrow to see its state at this step; click pins a node.',
  reasoningSummary: 'Ask the model for short summaries of its internal reasoning and keep them in the trace ("thinks" steps). No effect on behaviour or cost: only enabled for models that think by default (Claude 5.x).',
  traceKinds: 'run — the whole run, node — one agent activation, llm — a model call, tool — a tool call, message — a message along an arrow (including direct messages and board posts), thought — model reasoning or the think tool, inject — messages delivered to an agent mid-turn.',
}

const RU: typeof EN = {
  connectAs: 'Тип связи, который получит новая стрелка. Тяните от правой точки узла к левой точке другого. Тип можно поменять потом, кликнув по стрелке.',
  run: 'Один прогон графа на задаче, которую вы введёте. Удобно для отладки: узлы подсвечиваются по ходу выполнения, затем можно открыть трейс.',
  evaluate: 'Прогнать граф на всём датасете и посчитать точность, время, токены и стоимость. Результат появится в Experiments.',
  palette: 'Input — откуда приходит задача. Agent — LLM с инструментами. Vote — голосование большинством по ответам. Board — доска сообщений для группы агентов. Output — итоговый ответ, он и оценивается.',

  model: 'Какая LLM управляет агентом. Модели добавляются на странице Models; mock работает без ключей и годится для проверки графа.',
  systemPrompt: 'Роль и правила агента. К нему автоматически дописывается контекст: имя агента, общий workspace и инструменты, появившиеся из связей (это отключается ниже).',
  tools: 'Что агент может делать в песочнице. Ход агента заканчивается, когда модель отвечает текстом без вызова инструментов — этот текст и есть его выход. think полезен моделям без встроенного рассуждения: мысли попадают в трейс.',
  generatedTools: 'Эти инструменты агент получает автоматически из связей графа: handoff/delegate/message к другим агентам, post/read для досок. Настраивать их не нужно — меняйте связи.',
  maxSteps: 'Сколько раз за одну активацию агент может обратиться к модели (каждый вызов инструментов — ещё один шаг). Защищает от бесконечных циклов.',
  maxTokens: 'Лимит токенов на один ответ модели. Пусто — 16000.',
  effort: 'Насколько глубоко модель думает (Anthropic effort / OpenAI reasoning_effort). Ниже — быстрее и дешевле, выше — точнее на сложных задачах.',
  temperature: 'Случайность генерации. Новые модели Anthropic этот параметр не принимают — оставьте пустым, если не уверены.',
  memory: 'persistent — агент помнит всю свою переписку между активациями (важно для циклов «решатель ⇄ критик»). fresh — каждая активация начинается с чистого листа.',
  join: 'all — агент ждёт, пока закончат все узлы выше по графу, и получает все сообщения разом. any — запускается на каждое входящее сообщение отдельно.',
  includeTask: 'Добавлять исходную задачу в первое сообщение агенту. Выключите, если агент должен видеть только то, что ему передали другие.',
  autoContext: 'Дописывать к системному промпту служебный контекст о роли и инструментах. Выключите для полного контроля над промптом в экспериментах.',

  edgeKind: 'flow — передать выход дальше. conditional — передать, если выполнено условие. feedback — обратная стрелка для циклов. handoff — агент сам решает передать управление. delegate — агент вызывает другого как под-агента. message — агент может написать другому в любой момент, не заканчивая ход. subscribe — агент получает посты доски: от всех или только от выбранных авторов.',
  bidirectional: 'Двусторонняя связь: оба агента получают инструмент, чтобы писать друг другу. Для доски — агент и пишет в неё, и получает её посты.',
  subscribe: 'Подписка на доску: новый пост приходит агенту сообщением. Если агент сейчас работает — перед следующим вызовом модели, если свободен — он запускается.',
  filesDir: 'Папка на этой машине, которая копируется в песочницу каждой задачи перед запуском — для задач, у которых нет своего поля files. Относительный путь считается от корня проекта. Можно подставлять поля задачи: tasks/{id}. Папка копируется при каждом прогоне, в трейсе сохраняются список файлов и их хэш.',
  filesGlob: 'Какие файлы папки брать. Несколько шаблонов через «;». Без «/» — по имени файла на любой глубине (*.py), с «/» — путь от корня папки (src/**/*.ts), «re:…» — регулярное выражение по относительному пути, «!» в начале — исключить (!**/node_modules/**). Пусто — вся папка.',
  subscribeAuthors: 'Чьи посты доставлять подписчику. «everyone» — все посты; если отметить авторов, придут только их посты. Остальные посты агент по-прежнему может прочитать инструментом read_<доска>.',
  board: 'Доска — общий канал группы. Писать в неё могут агенты со связью Message, получать посты — агенты со связью Subscribe. Удобно для broadcast-координации без жёсткой схемы «кто кому».',
  condition: 'Проверяется на тексте выхода источника. contains / not contains — без учёта регистра; regex — регулярное выражение.',
  maxIterations: 'Сколько раз сообщение может пройти по этой обратной связи за прогон. После лимита цикл останавливается.',
  toolDescription: 'Подсказка агенту, когда вызывать этот handoff/delegate/message-инструмент. Попадает в описание инструмента.',

  sandbox: 'Где выполняются команды агентов. Docker — изолированный контейнер без сети (рекомендуется). Local — прямо на вашей машине в каталоге прогона.',
  network: 'Разрешить контейнеру выход в интернет (pip install, загрузка данных). По умолчанию выключено.',
  setup: 'Команда, которая выполняется в песочнице перед каждой задачей — например, установка зависимостей.',
  maxActivations: 'Общий лимит запусков агентов за прогон, включая делегирование. Защита от зацикленных графов.',
  runTimeout: 'Максимальное время одного прогона. После него берётся последний полученный ответ.',

  scorer: 'Как сравнивать ответ с эталоном. auto подходит в большинстве случаев: числа сравниваются численно, текст — точно или по вхождению. Ответ извлекается из <answer>…</answer>.',
  concurrency: 'Сколько задач датасета выполняется одновременно. Больше — быстрее, но легче упереться в rate limit провайдера.',
  repeats: 'Сколько раз прогнать каждую задачу. Несколько повторов показывают разброс результатов у недетерминированных агентов.',

  price: 'Цена за миллион токенов — нужна, чтобы считать стоимость прогонов. Посмотрите её на странице цен провайдера.',
  fallback: 'Если модель отказывается отвечать по соображениям безопасности, Anthropic может переотправить запрос другой модели. Для чистого сравнения моделей лучше выключить.',
  promptCache: 'Кэширование повторяющегося начала диалога. Агентские циклы каждый шаг отправляют всю историю заново — кэш заметно снижает стоимость.',

  replay: 'Пошаговое воспроизведение прогона. ← → — шаг назад/вперёд, Space — автовоспроизведение, Home/End — начало/конец. Наведите на узел или стрелку, чтобы увидеть их состояние на этом шаге; клик закрепляет узел.',
  reasoningSummary: 'Просить у модели краткие пересказы её внутреннего рассуждения и сохранять их в трейс (шаги «thinks»). На поведение и стоимость не влияет: включается только у моделей, которые и так думают по умолчанию (Claude 5.x).',
  traceKinds: 'run — весь прогон, node — одна активация агента, llm — вызов модели, tool — вызов инструмента, message — сообщение по стрелке (в том числе прямое и пост на доске), thought — рассуждение модели или инструмент think, inject — сообщения, доставленные агенту посреди хода.',
}

export const HINTS = LANG === 'ru' ? RU : EN
