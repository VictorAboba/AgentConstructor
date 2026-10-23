import { useState } from 'react'
import { api } from './api'
import Guide, { shouldAutoOpenGuide } from './Guide'
import Datasets from './pages/Datasets'
import { Compare, ExperimentList, ExperimentView } from './pages/Experiments'
import GraphEditor from './pages/GraphEditor'
import Models from './pages/Models'
import RunView from './pages/RunView'
import { Mark, Pill, ago, fmtCost, fmtMs, fmtTok, go, useHashRoute, usePoll } from './ui'

const NAV = [
  { key: 'graphs', label: 'Graphs', icon: '◇' },
  { key: 'runs', label: 'Runs', icon: '▸' },
  { key: 'experiments', label: 'Experiments', icon: '▦' },
  { key: 'datasets', label: 'Datasets', icon: '≡' },
  { key: 'models', label: 'Models', icon: '○' },
]

function Runs() {
  const { data, reload } = usePoll(() => api.runs('?adhoc=true'), [], 1500, (rs) => rs.some((r) => ['queued', 'running'].includes(r.status)))
  return (
    <div className="page">
      <div className="page-head"><h1>Runs</h1><span className="muted">single-task runs started from the editor</span></div>
      {!data?.length ? <div className="empty">No runs yet. Open a graph and press ▶ Run.</div> : (
        <table className="t">
          <thead><tr><th></th><th>Status</th><th>Graph</th><th>Task</th><th>Answer</th><th className="num">Time</th><th className="num">Tokens</th><th className="num">Cost</th><th>Started</th><th></th></tr></thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.id} className="click" onClick={() => go(`runs/${r.id}`)}>
                <td><Mark v={r.correct} /></td><td><Pill status={r.status} /></td><td>{r.graph_name}</td>
                <td className="clip" style={{ maxWidth: 300 }}>{r.task}</td>
                <td className="clip mono small" style={{ maxWidth: 240 }}>{r.answer ?? <span className="c-red">{r.error}</span>}</td>
                <td className="num">{fmtMs(r.duration_ms)}</td><td className="num">{fmtTok(r.input_tokens + r.output_tokens)}</td>
                <td className="num">{fmtCost(r.cost)}</td><td className="small muted">{ago(r.created_at)}</td>
                <td onClick={(e) => e.stopPropagation()}><button className="sm ghost danger" onClick={async () => { await api.deleteRun(r.id); reload() }}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function App() {
  const [section = 'graphs', id] = useHashRoute()
  const active = section === 'compare' ? 'experiments' : section
  const [guide, setGuide] = useState(shouldAutoOpenGuide)
  return (
    <div className="app">
      <nav className="side">
        <div className="brand"><span className="brand-mark" />AgentConstructor</div>
        {NAV.map((n) => (
          <a key={n.key} href={`#/${n.key}`} className={`nav ${active === n.key ? 'active' : ''}`}><span style={{ width: 14, textAlign: 'center' }}>{n.icon}</span>{n.label}</a>
        ))}
        <button className="ghost" style={{ marginTop: 'auto', justifyContent: 'flex-start' }} onClick={() => setGuide(true)}><span className="tip" style={{ marginLeft: 0 }}>?</span>Guide</button>
        <div className="side-foot" style={{ marginTop: 0 }}>no-code lab for multi-agent systems</div>
      </nav>
      <main className="main" style={section === 'graphs' ? { overflow: 'hidden' } : undefined}>
        {section === 'graphs' && <GraphEditor key="editor" id={id} />}
        {section === 'runs' && (id ? <RunView id={id} /> : <Runs />)}
        {section === 'experiments' && (id ? <ExperimentView id={id} /> : <ExperimentList />)}
        {section === 'compare' && <Compare />}
        {section === 'datasets' && <Datasets id={id} />}
        {section === 'models' && <Models />}
      </main>
      {guide && <Guide onClose={() => setGuide(false)} />}
    </div>
  )
}
