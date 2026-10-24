import { useEffect, useState } from 'react'
import { api } from './api'
import { tr } from './i18n'
import { Modal } from './ui'

const SEEN = 'ac.guideSeen'
export const markFlag = (k: string) => { try { localStorage.setItem(k, '1') } catch { /* storage unavailable */ } }
const flag = (k: string) => { try { return localStorage.getItem(k) === '1' } catch { return false } }
export const shouldAutoOpenGuide = () => !flag(SEEN)

interface Check { title: string; text: string; href: string; done: boolean }

async function progress(): Promise<Check[]> {
  const [models, graphs, runs, datasets, exps] = await Promise.all([
    api.models(), api.graphs(), api.runs('?adhoc=true&limit=20'), api.datasets(), api.experiments(),
  ])
  const real = new Set(models.filter((m) => m.provider !== 'mock').map((m) => m.id))
  const full = await Promise.all(graphs.slice(0, 30).map((g) => api.graph(g.id)))
  const realGraph = full.some((g) => g.data.nodes.some((n: any) => n.type === 'agent' && real.has(n.data?.model_id)))
  return [
    { title: tr('Connect a model', 'Подключите модель'), href: '#/models', done: real.size > 0,
      text: tr('Models → Add model: provider, model name, key. Test checks the connection. The mock model needs no key — use it to check graphs.',
        'Models → Add model: провайдер, имя модели, ключ. Кнопка Test проверит соединение. Mock-модель работает без ключа — для проверки графов.') },
    { title: tr('Build a graph', 'Соберите граф'), href: '#/graphs', done: realGraph,
      text: tr('Easiest is a template: New → pick a typical architecture (pipeline, orchestrator, hierarchy, debate, swarm, board…). Nodes come from the panel on the left; drag an arrow from a node\'s right handle to another\'s left one; the arrow kind is set by "connect as".',
        'Проще всего начать с шаблона: New → выберите типичную архитектуру (конвейер, оркестратор, иерархия, дебаты, рой, доска…). Узлы добавляются из панели слева, стрелка тянется от правой точки узла к левой; тип стрелки — в «connect as».') },
    { title: tr('Run it on one task', 'Запустите на одной задаче'), href: '#/graphs', done: runs.some((r) => r.status === 'done'),
      text: tr('▶ Run → type a task. Nodes light up as they work: orange — running, green — done, red — error.',
        '▶ Run → введите задачу. Узлы подсвечиваются по ходу работы: оранжевый — выполняется, зелёный — готово, красный — ошибка.') },
    { title: tr('Step through the trace', 'Разберите трейс по шагам'), href: '#/runs', done: flag('ac.replaySeen'),
      text: tr('Open a run → Step-by-step tab. Use ← → to walk through the steps and see who passed what to whom and what it cost.',
        'Откройте прогон → вкладка Step-by-step. Стрелками ← → можно идти по шагам и смотреть, кто кому что передал и сколько это стоило.') },
    { title: tr('Upload a dataset', 'Загрузите датасет'), href: '#/datasets', done: datasets.some((d) => d.name !== 'toy-arithmetic'),
      text: tr('JSONL/JSON/CSV with task and answer fields. The Datasets page shows an example.',
        'JSONL/JSON/CSV с полями task и answer. Пример формата есть на странице Datasets.') },
    { title: tr('Run an experiment', 'Запустите эксперимент'), href: '#/graphs', done: exps.length > 0,
      text: tr('"Evaluate on dataset" in the editor runs the graph over every task and measures accuracy, time, tokens and cost.',
        '«Evaluate on dataset» в редакторе: граф прогоняется по всем задачам, считаются точность, время, токены и стоимость.') },
    { title: tr('Compare variants', 'Сравните варианты'), href: '#/experiments', done: flag('ac.compareSeen'),
      text: tr('Duplicate the graph, change the model or the wiring, run it on the same dataset, then select both experiments → Compare.',
        'Сделайте копию графа (Duplicate), поменяйте модель или схему связей, прогоните на том же датасете и выберите оба эксперимента → Compare.') },
  ]
}

export default function Guide({ onClose }: { onClose: () => void }) {
  const [checks, setChecks] = useState<Check[] | null>(null)
  useEffect(() => { markFlag(SEEN); progress().then(setChecks).catch(() => setChecks([])) }, [])
  const done = checks?.filter((c) => c.done).length ?? 0
  return (
    <Modal title={tr('Getting started', 'Как начать')} onClose={onClose}>
      <div className="callout"><span>{tr('AgentConstructor is a lab for multi-agent systems: build a graph of agents, run it on tasks and measure how well, how fast and how cheaply it works.',
        'AgentConstructor — лаборатория для мультиагентных систем: собираете граф из агентов, прогоняете его на задачах и измеряете, насколько хорошо, быстро и дорого он работает.')}</span></div>
      {checks && <div className="row small muted"><div className="bar" style={{ flex: 1 }}><div style={{ width: `${(done / checks.length) * 100}%`, background: 'var(--green)' }} /></div>{done} / {checks.length}</div>}
      <div>
        {checks?.map((c, i) => (
          <div key={c.title} className="guide-step">
            <div className={`guide-num ${c.done ? 'done' : ''}`}>{c.done ? '✓' : i + 1}</div>
            <div><b>{c.title}</b><div className="small muted" style={{ marginTop: 2 }}>{c.text}</div></div>
            <a className="btn" href={c.href} onClick={onClose} style={{ padding: '3px 8px', fontSize: 12 }}>Open</a>
          </div>
        )) ?? <span className="muted">…</span>}
      </div>
      <h3 style={{ marginTop: 6 }}>{tr('Glossary', 'Словарик')}</h3>
      <div className="kv" style={{ gridTemplateColumns: '120px 1fr' }}>
        <div>{tr('Activation', 'Активация')}</div><div>{tr('One launch of an agent: it receives incoming messages and works until it hands in an answer.', 'Один запуск агента: он получает входящие сообщения и работает, пока не сдаст ответ.')}</div>
        <div>{tr('Agent step', 'Шаг агента')}</div><div>{tr('One model call within an activation; if the model called tools, their results go into the next step.', 'Один вызов модели внутри активации; если модель вызвала инструменты, их результаты уходят в следующий шаг.')}</div>
        <div>{tr('Span', 'Спан')}</div><div>{tr('A trace record with start, end, tokens and data: run, activation, LLM call, tool, message.', 'Запись в трейсе с началом, концом, токенами и данными: прогон, активация, LLM-вызов, инструмент, сообщение.')}</div>
        <div>{tr('Sandbox', 'Песочница')}</div><div>{tr('An isolated folder (and Docker container) where a run\'s agents execute commands and work with files.', 'Изолированный каталог (и Docker-контейнер), в котором агенты прогона выполняют команды и работают с файлами.')}</div>
      </div>
      <div className="small muted">{tr('The', 'Значки')} <span className="tip" style={{ cursor: 'default' }}>?</span> {tr('badges next to fields explain every setting. This window opens with the Guide button at the bottom left.', 'рядом с полями объясняют каждую настройку. Это окно открывается кнопкой «Guide» внизу слева.')}</div>
    </Modal>
  )
}
