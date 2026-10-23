import { ReactNode, useEffect, useMemo, useState } from 'react'
import { ModelCfg, Run, Span, api } from '../api'
import { HINTS } from '../hints'
import Replay from './Replay'
import { Mark, Pill, Stat, Tip, fmtCost, fmtMs, fmtNum, fmtTime, fmtTok, go, usePoll } from '../ui'

export function nodeStatuses(run: Run): Record<string, 'running' | 'ok' | 'error'> {
  const out: Record<string, 'running' | 'ok' | 'error'> = {}
  for (const s of run.spans || []) {
    if (!s.node_id || !['node', 'vote'].includes(s.kind)) continue
    out[s.node_id] = s.status === 'running' ? 'running' : s.status === 'error' ? 'error' : 'ok'
  }
  return out
}

const KINDS = ['run', 'sandbox', 'node', 'llm', 'thought', 'tool', 'message', 'inject', 'vote', 'judge', 'limit', 'warning']

export default function RunView({ id }: { id: string }) {
  const { data: run, error } = usePoll(() => api.run(id), [id], 1000, (r) => ['queued', 'running'].includes(r.status))
  const [tab, setTab] = useState<'trace' | 'replay' | 'messages' | 'files' | 'raw'>('trace')
  const [models, setModels] = useState<Record<string, ModelCfg>>({})
  useEffect(() => { api.models().then((ms) => setModels(Object.fromEntries(ms.map((m) => [m.id, m])))) }, [])

  if (error) return <div className="page"><div className="err">{error}</div></div>
  if (!run) return <div className="page muted">Loading…</div>
  const live = ['queued', 'running'].includes(run.status)
  const elapsed = run.duration_ms ?? (run.started_at ? Date.now() - run.started_at * 1000 : null)

  return (
    <div className="page">
      <div className="page-head">
        {run.experiment_id && <a className="muted" href={`#/experiments/${run.experiment_id}`}>← experiment</a>}
        <h1>{run.graph_name || 'Run'}</h1>
        <Pill status={run.status} />
        {run.correct != null && <Mark v={run.correct} />}
        <span className="mono small faint">{run.id}</span>
        <span className="spacer" />
        {live && <button className="danger" onClick={() => api.cancelRun(run.id)}>Stop</button>}
        <a className="btn" href={`/api/runs/${run.id}/export`}>Export JSON</a>
        {!run.experiment_id && <button className="ghost" onClick={() => go(`graphs/${run.graph_id}`)}>Open graph</button>}
      </div>

      <div className="cards">
        <Stat k="Duration" v={fmtMs(elapsed)} s={fmtTime(run.started_at)} />
        <Stat k="Tokens" v={fmtTok(run.input_tokens + run.output_tokens)} s={`${fmtTok(run.input_tokens)} in · ${fmtTok(run.output_tokens)} out${run.cached_tokens ? ` · ${fmtTok(run.cached_tokens)} cached` : ''}`} />
        <Stat k="Cost" v={fmtCost(run.cost)} />
        <Stat k="LLM calls" v={fmtNum(run.llm_calls)} />
        <Stat k="Tool calls" v={fmtNum(run.tool_calls)} />
        <Stat k="Activations" v={fmtNum(run.activations)} />
      </div>

      <div className="grid2" style={{ marginTop: 14 }}>
        <div className="card col"><h3>Task</h3><div className="answer">{run.task}</div></div>
        <div className="card col">
          <h3>Answer {run.expected != null && <span className="muted" style={{ fontWeight: 400 }}>· expected <span className="mono">{run.expected}</span></span>}</h3>
          <div className={`answer ${run.correct == null ? '' : run.correct ? 'yes' : 'no'}`}>{run.answer ?? (live ? '…' : '—')}</div>
          {run.judge_note && <span className="small muted">{run.judge_note}</span>}
          {run.error && <div className="err">{run.error}</div>}
        </div>
      </div>

      <div className="tabs">
        {(['trace', 'replay', 'messages', 'files', 'raw'] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {{ trace: 'Trace', replay: 'Step-by-step', messages: 'Agent messages', files: 'Workspace', raw: 'Node stats' }[t]}
          </button>
        ))}
      </div>
      {tab === 'trace' && <Trace spans={run.spans || []} live={live} />}
      {tab === 'replay' && <Replay run={run} models={models} />}
      {tab === 'messages' && <Messages spans={run.spans || []} />}
      {tab === 'files' && <Workspace runId={run.id} live={live} />}
      {tab === 'raw' && <NodeTable run={run} />}
    </div>
  )
}

// ---- trace waterfall ----------------------------------------------------------------------

function orderSpans(spans: Span[]): { span: Span; depth: number }[] {
  const ids = new Set(spans.map((s) => s.id))
  const children: Record<string, Span[]> = {}
  const roots: Span[] = []
  for (const s of spans) {
    if (s.parent_id && ids.has(s.parent_id)) (children[s.parent_id] ||= []).push(s)
    else roots.push(s)
  }
  const out: { span: Span; depth: number }[] = []
  const walk = (s: Span, depth: number) => {
    out.push({ span: s, depth })
    for (const c of (children[s.id] || []).sort((a, b) => a.started_at - b.started_at)) walk(c, depth + 1)
  }
  roots.sort((a, b) => a.started_at - b.started_at).forEach((r) => walk(r, 0))
  return out
}

function Trace({ spans, live }: { spans: Span[]; live: boolean }) {
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<string | null>(null)
  const rows = useMemo(() => orderSpans(spans).filter((r) => !hidden.has(r.span.kind)), [spans, hidden])
  if (!spans.length) return <div className="empty">No spans yet.</div>
  const t0 = Math.min(...spans.map((s) => s.started_at))
  const now = Date.now() / 1000
  const t1 = Math.max(...spans.map((s) => s.ended_at ?? (live ? now : s.started_at)), t0 + 0.001)
  const total = t1 - t0
  const selected = spans.find((s) => s.id === sel)
  const present = KINDS.filter((k) => spans.some((s) => s.kind === k))

  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        {present.map((k) => (
          <label key={k} className="check"><input type="checkbox" checked={!hidden.has(k)} onChange={() => {
            const h = new Set(hidden); h.has(k) ? h.delete(k) : h.add(k); setHidden(h)
          }} /><span className="mono">{k}</span></label>
        ))}
        <Tip text={HINTS.traceKinds} />
        <span className="spacer" /><span className="small muted">{spans.length} spans · {fmtMs(total * 1000)}</span>
      </div>
      <div className="trace">
        <div className="wf">
          {rows.map(({ span: s, depth }) => {
            const end = s.ended_at ?? (s.status === 'running' ? now : s.started_at)
            const left = ((s.started_at - t0) / total) * 100
            const width = Math.max(((end - s.started_at) / total) * 100, 0.15)
            const tok = s.input_tokens + s.output_tokens
            return (
              <div key={s.id} className={`wf-row ${sel === s.id ? 'sel' : ''}`} onClick={() => setSel(s.id)}>
                <div className="wf-name" style={{ paddingLeft: depth * 14 }}>
                  <span className="wf-kind">{s.kind}</span>
                  <span className={s.status === 'error' ? 'c-red' : ''}>{s.name}</span>
                  {tok > 0 && <span className="small faint mono">{fmtTok(tok)}</span>}
                </div>
                <div className="wf-track"><div className={`wf-bar k-${s.kind} s-${s.status}`} style={{ left: `${left}%`, width: `${width}%` }} /></div>
                <div className="wf-dur">{s.duration_ms ? fmtMs(s.duration_ms) : s.status === 'running' ? '…' : ''}</div>
              </div>
            )
          })}
        </div>
        <div className="detail">{selected ? <SpanDetail s={selected} spans={spans} /> : <span className="muted">Select a span to inspect inputs, outputs and token usage.</span>}</div>
      </div>
    </>
  )
}

const Block = ({ title, children, extra }: { title: string; children: ReactNode; extra?: ReactNode }) => (
  <div className="block"><div className="bh">{title}<span className="spacer" />{extra}</div><div className="bb">{children}</div></div>
)
/** Collapsible block for long, rarely needed content such as system prompts. */
const Fold = ({ title, children, open = false, extra }: { title: string; children: ReactNode; open?: boolean; extra?: ReactNode }) => (
  <details className="block" open={open}><summary><div className="bh">{title}<span className="spacer" />{extra}</div></summary><div className="bb">{children}</div></details>
)

/** System prompt and tool list in effect for a span: its own, else the enclosing agent activation's. */
function agentContext(s: Span, spans: Span[]): { system?: string; tools?: string[]; inherited: boolean } {
  if (s.data?.system) return { system: s.data.system, tools: s.data.tools, inherited: false }
  let p = spans.find((x) => x.id === s.parent_id)
  while (p && p.kind !== 'node') p = spans.find((x) => x.id === p!.parent_id)
  return p ? { system: p.data?.system, tools: p.data?.tools, inherited: true } : { inherited: false }
}
const J = ({ v }: { v: any }) => <pre>{typeof v === 'string' ? v : JSON.stringify(v, null, 2)}</pre>

function ChatMessages({ msgs }: { msgs: any[] }) {
  return (
    <div className="col">
      {msgs.map((m, i) => (
        <div key={i}>
          <div className="small mono muted">{m.role}{m.name ? ` · ${m.name}` : ''}{m.is_error ? ' · error' : ''}</div>
          {m.content && <pre className={m.is_error ? 'c-red' : ''}>{m.content}</pre>}
          {m.tool_calls?.length > 0 && <J v={m.tool_calls} />}
        </div>
      ))}
    </div>
  )
}

export function SpanDetail({ s, spans }: { s: Span; spans: Span[] }) {
  const d = s.data || {}
  const ctx = ['llm', 'node'].includes(s.kind) ? agentContext(s, spans) : null
  return (
    <>
      <div className="row"><span className="mono small muted">{s.kind}</span><h3 style={{ margin: 0 }}>{s.name}</h3><Pill status={s.status} /></div>
      <div className="kv">
        <div>Duration</div><div className="mono">{fmtMs(s.duration_ms)}</div>
        {s.node_id && <><div>Node</div><div className="mono">{s.node_id}</div></>}
        {(s.input_tokens > 0 || s.output_tokens > 0) && <><div>Tokens</div><div className="mono">{fmtNum(s.input_tokens)} in · {fmtNum(s.output_tokens)} out{d.cached_tokens ? ` · ${fmtNum(d.cached_tokens)} cached` : ''}</div></>}
        {s.cost > 0 && <><div>Cost</div><div className="mono">{fmtCost(s.cost)}</div></>}
        {d.model && <><div>Model</div><div className="mono">{d.model}{d.served_by && d.served_by !== d.model ? <span className={d.notes?.some((n: string) => n.startsWith('fallback')) ? 'c-orange' : 'muted'}> → served by {d.served_by}</span> : null}</div></>}
        {d.stop_reason && <><div>Stop reason</div><div className="mono">{d.stop_reason}</div></>}
        {d.step && <><div>Step</div><div className="mono">{d.step}</div></>}
      </div>
      {d.error && <div className="err">{d.error}</div>}
      {d.notes && <Block title="Notes"><J v={d.notes} /></Block>}
      {s.kind === 'llm' && (
        <>
          {ctx?.system && <Fold title="System prompt" open={!ctx.inherited} extra={ctx.inherited ? 'same as step 1' : `${ctx.system.length} chars`}><pre>{ctx.system}</pre></Fold>}
          {ctx?.tools && <Block title="Tools offered"><span className="mono small">{ctx.tools.join(', ') || '—'}</span></Block>}
          {d.new_messages?.length > 0 && <Block title="New input since previous call"><ChatMessages msgs={d.new_messages} /></Block>}
          {d.reasoning && <Block title="Reasoning"><pre className="muted">{d.reasoning}</pre></Block>}
          {d.text && <Block title="Response"><pre>{d.text}</pre></Block>}
          {d.tool_calls?.length > 0 && <Block title="Tool calls"><J v={d.tool_calls} /></Block>}
        </>
      )}
      {s.kind === 'tool' && (<><Block title="Arguments"><J v={d.arguments} /></Block><Block title="Result"><pre>{d.result}</pre></Block></>)}
      {s.kind === 'node' && (
        <>
          {ctx?.system && <Fold title="System prompt" open extra={`${ctx.system.length} chars`}><pre>{ctx.system}</pre></Fold>}
          {ctx?.tools && <Block title={`Tools · memory ${d.memory ?? 'persistent'}${d.history_messages ? ` · ${d.history_messages} earlier messages` : ''}`}><span className="mono small">{ctx.tools.join(', ') || '—'}</span></Block>}
          <Block title={`Input · activation ${d.activation ?? ''}`}><pre>{d.input}</pre></Block>
          {d.output != null && <Block title={`Output · ${d.status || ''} · ${d.steps ?? ''} steps`}><pre>{d.output}</pre></Block>}
        </>
      )}
      {s.kind === 'message' && <Block title={`${d.kind} message${d.author ? ` · by ${d.author}` : ''}`}><pre>{d.content}</pre></Block>}
      {s.kind === 'thought' && <Block title={d.source === 'think tool' ? 'Thought · think tool' : 'Reasoning · model (summary)'}><pre className="muted">{d.text}</pre></Block>}
      {s.kind === 'inject' && <Block title="Delivered mid-turn, before the next model call"><ChatMessages msgs={(d.messages || []).map((m: any) => ({ role: `${m.kind} from ${m.source_label}`, content: m.content }))} /></Block>}
      {!['llm', 'tool', 'node', 'message', 'thought', 'inject'].includes(s.kind) && <Block title="Data"><J v={d} /></Block>}
    </>
  )
}

// ---- other tabs ---------------------------------------------------------------------------

function Messages({ spans }: { spans: Span[] }) {
  const [thoughts, setThoughts] = useState(true)
  const items = spans.filter((s) => s.kind === 'message' || (s.kind === 'node' && s.status !== 'running') || s.kind === 'vote' || (thoughts && s.kind === 'thought'))
  if (!items.length) return <div className="empty">No messages yet.</div>
  const t0 = Math.min(...spans.map((s) => s.started_at))
  return (
    <div className="card">
      <label className="check" style={{ marginBottom: 10 }}><input type="checkbox" checked={thoughts} onChange={(e) => setThoughts(e.target.checked)} />Show thoughts (model reasoning and think tool)</label>
      {items.map((s) => {
        const d = s.data || {}
        if (s.kind === 'thought') return (
          <div key={s.id} className="msg k-thought">
            <div className="mh muted"><span>💭 {s.name}</span><span className="small faint">{d.source}</span><span className="small faint mono">+{fmtMs((s.started_at - t0) * 1000)}</span></div>
            <pre>{d.text}</pre>
          </div>
        )
        if (s.kind === 'message') return (
          <div key={s.id} className={`msg k-${d.kind}`}>
            <div className="mh"><span>{s.name}</span><span className="pill">{d.kind}</span><span className="small faint mono">+{fmtMs((s.started_at - t0) * 1000)}</span></div>
            <pre>{d.content}</pre>
          </div>
        )
        if (s.kind === 'vote') return (
          <div key={s.id} className="msg"><div className="mh"><span>🗳 {s.name}</span></div><J v={d.tally} /></div>
        )
        return (
          <div key={s.id} className="msg" style={{ borderLeftColor: 'var(--line-2)' }}>
            <div className="mh muted"><span>{s.name} finished activation {d.activation}</span><Pill status={s.status} /><span className="small faint mono">{fmtMs(s.duration_ms)} · {d.steps} steps</span></div>
          </div>
        )
      })}
    </div>
  )
}

function Workspace({ runId, live }: { runId: string; live: boolean }) {
  const files = usePoll(() => api.runFiles(runId), [runId], 2000, () => live)
  const [sel, setSel] = useState<string | null>(null)
  const [content, setContent] = useState<string>('')
  useEffect(() => { if (sel) api.runFile(runId, sel).then((f) => setContent(f.content)).catch((e) => setContent(e.message)) }, [sel, runId])
  if (!files.data?.length) return <div className="empty">Workspace is empty.</div>
  return (
    <div className="files">
      <div className="card" style={{ padding: 6 }}>
        {files.data.map((f) => (
          <div key={f.path} className={`file-item ${sel === f.path ? 'sel' : ''}`} onClick={() => setSel(f.path)}>
            <span>{f.path}</span><span className="faint">{f.size}</span>
          </div>
        ))}
      </div>
      <div className="card">{sel ? <pre>{content}</pre> : <span className="muted">Select a file.</span>}</div>
    </div>
  )
}

function NodeTable({ run }: { run: Run }) {
  const labels: Record<string, string> = Object.fromEntries((run.graph_snapshot?.nodes || []).map((n: any) => [n.id, n.data?.label || n.id]))
  const stats = Object.entries(run.node_stats || {})
  if (!stats.length) return <div className="empty">No node statistics yet.</div>
  return (
    <table className="t">
      <thead><tr><th>Node</th><th className="num">Activations</th><th className="num">LLM calls</th><th className="num">Tool calls</th>
        <th className="num">Input tok</th><th className="num">Output tok</th><th className="num">Cached</th><th className="num">Cost</th><th className="num">Time</th><th className="num">Errors</th></tr></thead>
      <tbody>
        {stats.map(([nid, s]) => (
          <tr key={nid}><td>{labels[nid] || nid}</td><td className="num">{s.activations}</td><td className="num">{s.llm_calls}</td><td className="num">{s.tool_calls}</td>
            <td className="num">{fmtNum(s.input_tokens)}</td><td className="num">{fmtNum(s.output_tokens)}</td><td className="num">{fmtNum(s.cached_tokens)}</td>
            <td className="num">{fmtCost(s.cost)}</td><td className="num">{fmtMs(s.duration_ms)}</td><td className={`num ${s.errors ? 'c-red' : ''}`}>{s.errors}</td></tr>
        ))}
      </tbody>
    </table>
  )
}
