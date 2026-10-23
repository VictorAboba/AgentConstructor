import { useEffect, useState } from 'react'
import { api } from './api'
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
    { title: 'Подключите модель', href: '#/models', done: real.size > 0,
      text: 'Models → Add model: провайдер, имя модели, ключ. Кнопка Test проверит соединение. Mock-модель работает без ключа — для проверки графов.' },
    { title: 'Соберите граф', href: '#/graphs', done: realGraph,
      text: 'Проще всего начать с шаблона: New → выберите типичную архитектуру (конвейер, оркестратор, иерархия, дебаты, рой, доска…). Узлы добавляются из панели слева, стрелка тянется от правой точки узла к левой; тип стрелки — в «connect as».' },
    { title: 'Запустите на одной задаче', href: '#/graphs', done: runs.some((r) => r.status === 'done'),
      text: '▶ Run → введите задачу. Узлы подсвечиваются по ходу работы: оранжевый — выполняется, зелёный — готово, красный — ошибка.' },
    { title: 'Разберите трейс по шагам', href: '#/runs', done: flag('ac.replaySeen'),
      text: 'Откройте прогон → вкладка Step-by-step. Стрелками ← → можно идти по шагам и смотреть, кто кому что передал и сколько это стоило.' },
    { title: 'Загрузите датасет', href: '#/datasets', done: datasets.some((d) => d.name !== 'toy-arithmetic'),
      text: 'JSONL/JSON/CSV с полями task и answer. Пример формата есть на странице Datasets.' },
    { title: 'Запустите эксперимент', href: '#/graphs', done: exps.length > 0,
      text: '«Evaluate on dataset» в редакторе: граф прогоняется по всем задачам, считаются точность, время, токены и стоимость.' },
    { title: 'Сравните варианты', href: '#/experiments', done: flag('ac.compareSeen'),
      text: 'Сделайте копию графа (Duplicate), поменяйте модель или схему связей, прогоните на том же датасете и выберите оба эксперимента → Compare.' },
  ]
}

export default function Guide({ onClose }: { onClose: () => void }) {
  const [checks, setChecks] = useState<Check[] | null>(null)
  useEffect(() => { markFlag(SEEN); progress().then(setChecks).catch(() => setChecks([])) }, [])
  const done = checks?.filter((c) => c.done).length ?? 0
  return (
    <Modal title="Как начать" onClose={onClose}>
      <div className="callout"><span>AgentConstructor — лаборатория для мультиагентных систем: собираете граф из агентов, прогоняете его на задачах и
        измеряете, насколько хорошо, быстро и дорого он работает.</span></div>
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
      <h3 style={{ marginTop: 6 }}>Словарик</h3>
      <div className="kv" style={{ gridTemplateColumns: '120px 1fr' }}>
        <div>Активация</div><div>Один запуск агента: он получает входящие сообщения и работает, пока не сдаст ответ.</div>
        <div>Шаг агента</div><div>Один вызов модели внутри активации; если модель вызвала инструменты, их результаты уходят в следующий шаг.</div>
        <div>Спан</div><div>Запись в трейсе с началом, концом, токенами и данными: прогон, активация, LLM-вызов, инструмент, сообщение.</div>
        <div>Песочница</div><div>Изолированный каталог (и Docker-контейнер), в котором агенты прогона выполняют команды и работают с файлами.</div>
      </div>
      <div className="small muted">Значки <span className="tip" style={{ cursor: 'default' }}>?</span> рядом с полями объясняют каждую настройку. Это окно открывается кнопкой «Guide» внизу слева.</div>
    </Modal>
  )
}
