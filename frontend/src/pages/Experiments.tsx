import { useEffect, useMemo, useState } from 'react'
import { Experiment, Summary, api } from '../api'
import { markFlag } from '../Guide'
import { Mark, Pill, Stat, ago, fmtCost, fmtMs, fmtNum, fmtPct, fmtTok, go, hashQuery, usePoll, useToast } from '../ui'

const isLive = (s: string) => ['queued', 'running'].includes(s)

export function ExperimentList() {
  const { data, reload } = usePoll(() => api.experiments(), [], 1500, (es) => es.some((e) => isLive(e.status)))
  const [sel, setSel] = useState<Set<string>>(new Set())
  const toggle = (id: string) => { const s = new Set(sel); s.has(id) ? s.delete(id) : s.add(id); setSel(s) }
  return (
    <div className="page">
      <div className="page-head">
        <h1>Experiments</h1><span className="muted">graph × dataset evaluations</span><span className="spacer" />
        <button className="primary" disabled={sel.size < 2} onClick={() => go(`compare?ids=${[...sel].join(',')}`)}>Compare {sel.size > 1 ? `(${sel.size})` : ''}</button>
      </div>
      {!data?.length ? <div className="empty">No experiments yet. Open a graph and press “Evaluate on dataset”.</div> : (
        <table className="t">
          <thead><tr><th></th><th>Name</th><th>Status</th><th>Progress</th><th className="num">Accuracy</th><th className="num">Mean time</th>
            <th className="num">Mean tokens</th><th className="num">Total cost</th><th>Created</th><th></th></tr></thead>
          <tbody>
            {data.map((e) => {
              const s = e.summary || ({} as Summary)
              return (
                <tr key={e.id} className="click" onClick={() => go(`experiments/${e.id}`)}>
                  <td onClick={(ev) => ev.stopPropagation()}><input type="checkbox" checked={sel.has(e.id)} onChange={() => toggle(e.id)} /></td>
                  <td style={{ minWidth: 200 }}><div>{e.name}</div><div className="small muted">{e.graph_name} · {e.dataset_name}{e.config?.repeats > 1 ? ` · ×${e.config.repeats}` : ''}</div></td>
                  <td><Pill status={e.status} /></td>
                  <td style={{ width: 120 }}><div className="bar"><div style={{ width: `${s.total ? (s.finished / s.total) * 100 : 0}%` }} /></div>
                    <span className="small muted mono">{s.finished ?? 0}/{s.total ?? 0}{s.errors ? <span className="c-red"> · {s.errors} err</span> : null}</span></td>
                  <td className="num">{fmtPct(s.accuracy)}</td><td className="num">{fmtMs(s.duration_mean_ms)}</td>
                  <td className="num">{fmtTok(s.tokens_mean)}</td><td className="num">{fmtCost(s.cost)}</td>
                  <td className="small muted">{ago(e.created_at)}</td>
                  <td onClick={(ev) => ev.stopPropagation()}><button className="sm ghost danger" onClick={async () => { if (confirm('Delete experiment and its traces?')) { await api.deleteExperiment(e.id); reload() } }}>✕</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function ExperimentView({ id }: { id: string }) {
  const toast = useToast()
  const { data: e, error } = usePoll(() => api.experiment(id), [id], 1500, (x) => isLive(x.status))
  const [filter, setFilter] = useState<'all' | 'correct' | 'wrong' | 'error'>('all')
  if (error) return <div className="page"><div className="err">{error}</div></div>
  if (!e) return <div className="page muted">Loading…</div>
  const s = e.summary
  const labels: Record<string, string> = Object.fromEntries((e.graph_snapshot?.nodes || []).map((n: any) => [n.id, n.data?.label || n.id]))
  const runs = (e.runs || []).filter((r) => filter === 'all' || (filter === 'correct' && r.correct === 1) || (filter === 'wrong' && r.correct === 0) || (filter === 'error' && r.status === 'error'))
  return (
    <div className="page">
      <div className="page-head">
        <a className="muted" href="#/experiments">← experiments</a>
        <h1>{e.name}</h1><Pill status={e.status} /><span className="spacer" />
        {isLive(e.status) && <button className="danger" onClick={() => api.cancelExperiment(e.id).then(() => toast('Cancelling…'))}>Stop</button>}
        <a className="btn" href={`/api/experiments/${e.id}/export?format=csv`}>CSV</a>
        <a className="btn" href={`/api/experiments/${e.id}/export?format=jsonl`}>JSONL</a>
        <button className="ghost" onClick={() => go(`graphs/${e.graph_id}`)}>Open graph</button>
      </div>
      <div className="small muted" style={{ marginBottom: 12 }}>
        graph <b>{e.graph_name}</b> · dataset <b>{e.dataset_name}</b> · scorer <span className="mono">{e.config?.scorer?.type}</span> ·
        concurrency {e.config?.concurrency} · repeats {e.config?.repeats}
      </div>
      <div className="cards">
        <Stat k="Accuracy" v={<span className={s.accuracy == null ? '' : s.accuracy >= 0.5 ? 'c-green' : 'c-red'}>{fmtPct(s.accuracy)}</span>} s={`${s.correct}/${s.scored} scored · ${s.finished}/${s.total} done`} />
        <Stat k="Latency" v={fmtMs(s.duration_mean_ms)} s={`median ${fmtMs(s.duration_median_ms)} · p95 ${fmtMs(s.duration_p95_ms)}`} />
        <Stat k="Tokens / task" v={fmtTok(s.tokens_mean)} s={`${fmtTok(s.input_tokens)} in · ${fmtTok(s.output_tokens)} out total`} />
        <Stat k="Cost" v={fmtCost(s.cost)} s={`${fmtCost(s.cost_mean)} / task${s.judge_cost ? ` · judge ${fmtCost(s.judge_cost)}` : ''}`} />
        <Stat k="LLM calls / task" v={fmtNum(s.llm_calls_mean, 1)} s={`${fmtNum(s.tool_calls_mean, 1)} tool calls`} />
        <Stat k="Errors" v={<span className={s.errors ? 'c-red' : ''}>{s.errors}</span>} s={s.running ? `${s.running} running` : undefined} />
      </div>

      {Object.keys(s.nodes || {}).length > 0 && (
        <>
          <h2>Per agent (mean per task)</h2>
          <table className="t">
            <thead><tr><th>Node</th><th className="num">Activations</th><th className="num">LLM calls</th><th className="num">Tool calls</th><th className="num">Tokens</th><th className="num">Share of tokens</th><th className="num">Time</th><th className="num">Cost</th><th className="num">Errors</th></tr></thead>
            <tbody>
              {Object.entries(s.nodes).map(([nid, n]) => {
                const k = s.finished || 1
                const tok = n.input_tokens + n.output_tokens
                const allTok = s.input_tokens + s.output_tokens || 1
                return (
                  <tr key={nid}><td>{labels[nid] || nid}</td><td className="num">{fmtNum(n.activations / k, 2)}</td><td className="num">{fmtNum(n.llm_calls / k, 2)}</td>
                    <td className="num">{fmtNum(n.tool_calls / k, 2)}</td><td className="num">{fmtTok(tok / k)}</td>
                    <td className="num" style={{ width: 140 }}><div className="row" style={{ justifyContent: 'flex-end' }}><div className="bar" style={{ width: 70 }}><div style={{ width: `${(tok / allTok) * 100}%` }} /></div>{fmtPct(tok / allTok)}</div></td>
                    <td className="num">{fmtMs(n.duration_ms / k)}</td><td className="num">{fmtCost(n.cost / k)}</td><td className={`num ${n.errors ? 'c-red' : ''}`}>{n.errors}</td></tr>
                )
              })}
            </tbody>
          </table>
        </>
      )}

      <div className="row" style={{ margin: '22px 0 10px' }}>
        <h2 style={{ margin: 0 }}>Tasks</h2><span className="spacer" />
        <div className="seg">{(['all', 'correct', 'wrong', 'error'] as const).map((f) => <button key={f} className={filter === f ? 'on' : ''} onClick={() => setFilter(f)}>{f}</button>)}</div>
      </div>
      <table className="t">
        <thead><tr><th>#</th><th></th><th>Status</th><th>Task</th><th>Expected</th><th>Answer</th><th className="num">Time</th><th className="num">Tokens</th><th className="num">Cost</th><th className="num">LLM / tools</th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="click" onClick={() => go(`runs/${r.id}`)}>
              <td className="mono small">{r.idx}{r.repeat ? `.${r.repeat}` : ''}</td>
              <td><Mark v={r.correct} /></td>
              <td><Pill status={r.status} /></td>
              <td className="clip" style={{ maxWidth: 280 }} title={r.task}>{r.task}</td>
              <td className="clip mono small" style={{ maxWidth: 120 }}>{r.expected}</td>
              <td className="clip mono small" style={{ maxWidth: 240 }} title={r.answer || r.error || ''}>{r.answer ?? <span className="c-red">{r.error}</span>}</td>
              <td className="num">{fmtMs(r.duration_ms)}</td><td className="num">{fmtTok(r.input_tokens + r.output_tokens)}</td>
              <td className="num">{fmtCost(r.cost)}</td><td className="num">{r.llm_calls} / {r.tool_calls}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type Metric = { key: string; label: string; get: (s: Summary) => number | null; fmt: (v: number | null) => string; better: 'high' | 'low' }
const METRICS: Metric[] = [
  { key: 'acc', label: 'Accuracy', get: (s) => s.accuracy, fmt: fmtPct, better: 'high' },
  { key: 'lat', label: 'Mean latency', get: (s) => s.duration_mean_ms, fmt: fmtMs, better: 'low' },
  { key: 'p95', label: 'p95 latency', get: (s) => s.duration_p95_ms, fmt: fmtMs, better: 'low' },
  { key: 'tok', label: 'Tokens / task', get: (s) => s.tokens_mean, fmt: fmtTok, better: 'low' },
  { key: 'cost', label: 'Cost / task', get: (s) => s.cost_mean, fmt: fmtCost, better: 'low' },
  { key: 'llm', label: 'LLM calls / task', get: (s) => s.llm_calls_mean, fmt: (v) => fmtNum(v, 1), better: 'low' },
  { key: 'tools', label: 'Tool calls / task', get: (s) => s.tool_calls_mean, fmt: (v) => fmtNum(v, 1), better: 'low' },
  { key: 'err', label: 'Errors', get: (s) => s.errors, fmt: (v) => fmtNum(v), better: 'low' },
  { key: 'cpa', label: 'Cost per correct answer', get: (s) => (s.correct ? s.cost / s.correct : null), fmt: fmtCost, better: 'low' },
]

export function Compare() {
  const ids = (hashQuery().get('ids') || '').split(',').filter(Boolean)
  useEffect(() => markFlag('ac.compareSeen'), [])
  const { data } = usePoll(() => Promise.all(ids.map((i) => api.experiment(i))), [ids.join(',')], 2000, (es) => es.some((e) => isLive(e.status)))
  const matrix = useMemo(() => {
    if (!data) return []
    const keys = new Map<string, string>()
    for (const e of data) for (const r of e.runs || []) keys.set(`${r.idx}`, r.task)
    return [...keys.entries()].sort((a, b) => +a[0] - +b[0]).map(([idx, task]) => ({
      idx, task, cells: data.map((e) => (e.runs || []).filter((r) => `${r.idx}` === idx)),
    }))
  }, [data])
  if (!data) return <div className="page muted">Loading…</div>
  return (
    <div className="page">
      <div className="page-head"><a className="muted" href="#/experiments">← experiments</a><h1>Compare</h1></div>
      <table className="t">
        <thead><tr><th>Metric</th>{data.map((e: Experiment) => <th key={e.id} className="num"><a href={`#/experiments/${e.id}`}>{e.name}</a><div className="small faint" style={{ textTransform: 'none' }}>{e.dataset_name}</div></th>)}</tr></thead>
        <tbody>
          {METRICS.map((m) => {
            const vals = data.map((e) => m.get(e.summary))
            const valid = vals.filter((v): v is number => v != null)
            const best = valid.length > 1 ? (m.better === 'high' ? Math.max(...valid) : Math.min(...valid)) : null
            const worst = valid.length > 1 ? (m.better === 'high' ? Math.min(...valid) : Math.max(...valid)) : null
            return (
              <tr key={m.key}><td>{m.label}</td>
                {vals.map((v, i) => <td key={i} className={`num ${v != null && v === best && best !== worst ? 'best' : ''} ${v != null && v === worst && best !== worst ? 'c-red' : ''}`}>{m.fmt(v)}</td>)}
              </tr>
            )
          })}
        </tbody>
      </table>
      <h2>Per task</h2>
      <table className="t matrix">
        <thead><tr><th>#</th><th style={{ textAlign: 'left' }}>Task</th>{data.map((e) => <th key={e.id} className="num" style={{ textAlign: 'center' }}>{e.name}</th>)}</tr></thead>
        <tbody>
          {matrix.map((row) => (
            <tr key={row.idx}><td className="mono small">{row.idx}</td><td className="clip" style={{ textAlign: 'left', maxWidth: 360 }} title={row.task}>{row.task}</td>
              {row.cells.map((runs, i) => (
                <td key={i}>{runs.map((r) => <a key={r.id} href={`#/runs/${r.id}`} title={`${fmtMs(r.duration_ms)} · ${fmtTok(r.input_tokens + r.output_tokens)} tok`} style={{ textDecoration: 'none', marginRight: 4 }}>
                  {r.status === 'error' ? <span className="mark no">!</span> : <Mark v={r.correct} />}</a>)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
