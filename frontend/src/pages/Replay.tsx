import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ModelCfg, NodeStats, Run, Span } from '../api'
import { nodeTypes, styleEdge } from '../flow'
import { HINTS } from '../hints'
import { Pill, Tip, fmtCost, fmtMs, fmtNum, fmtTok } from '../ui'
import { markFlag } from '../Guide'
import { SpanDetail } from './RunView'

type StepKind = 'sandbox' | 'start' | 'thought' | 'inject' | 'llm' | 'tool' | 'message' | 'end' | 'vote' | 'note' | 'judge' | 'finish'

interface Step {
  t: number
  kind: StepKind
  span: Span
  node?: string // node the step happens in (focus ring)
  edge?: string // edge traversed by the step (highlighted)
  target?: string // receiving node of a message / delegation
  title: string
}

// Same-timestamp ordering: a node finishes, then its messages go out, then the receiver starts.
const PRIORITY: Record<StepKind, number> = { sandbox: 0, end: 1, vote: 1, message: 2, start: 3, inject: 3.5, thought: 3.6, llm: 4, tool: 5, note: 6, judge: 8, finish: 9 }

interface NodeState {
  status?: 'running' | 'ok' | 'error' | 'waiting'
  inbox: number
  stats: NodeStats
  lastInput?: string
  lastOutput?: string
  lastText?: string
  lastTool?: string
  lastThought?: string
  posts?: number
}
interface EdgeState { count: number; last?: string }
interface Snapshot { nodes: Record<string, NodeState>; edges: Record<string, EdgeState> }

const emptyStats = (): NodeStats => ({ activations: 0, llm_calls: 0, tool_calls: 0, input_tokens: 0, output_tokens: 0, cached_tokens: 0, cost: 0, duration_ms: 0, errors: 0 })
const clip = (s: string | undefined, n = 90) => (s && s.length > n ? s.slice(0, n) + '…' : s || '')

function buildSteps(spans: Span[], graph: { nodes: any[]; edges: any[] }): Step[] {
  const label = (id?: string | null) => graph.nodes.find((n) => n.id === id)?.data?.label || id || '?'
  const byId = new Map(spans.map((s) => [s.id, s]))
  const steps: Step[] = []
  for (const s of spans) {
    const d = s.data || {}
    const end = s.ended_at ?? s.started_at
    switch (s.kind) {
      case 'sandbox':
        if (s.ended_at) steps.push({ t: end, kind: 'sandbox', span: s, title: `Sandbox ready: ${s.name}` })
        break
      case 'node': {
        const parent = s.parent_id ? byId.get(s.parent_id) : undefined
        const delegated = parent?.kind === 'tool' && parent.name.startsWith('ask_')
        const edge = delegated
          ? graph.edges.find((e) => e.source === parent!.node_id && e.target === s.node_id && e.data?.kind === 'delegate')?.id
          : undefined
        steps.push({ t: s.started_at, kind: 'start', span: s, node: s.node_id!, edge, target: s.node_id!,
          title: `${label(s.node_id)} starts activation #${d.activation ?? '?'}${delegated ? ` (delegated by ${label(parent!.node_id)})` : ''}` })
        if (s.ended_at) steps.push({ t: end, kind: 'end', span: s, node: s.node_id!,
          title: `${label(s.node_id)} finished · ${d.status || s.status}${d.handoff ? ` · hands off to ${label(d.handoff)}` : ''}${d.output ? ` — “${clip(d.output, 60)}”` : ''}` })
        break
      }
      case 'llm': {
        const calls: any[] = d.tool_calls || []
        const what = s.status === 'running' ? 'waiting for the model…' : calls.length ? `calls ${calls.map((c) => c.name).join(', ')}` : `answers “${clip(d.text, 60)}”`
        steps.push({ t: s.status === 'running' ? s.started_at : end, kind: 'llm', span: s, node: s.node_id!, title: `${label(s.node_id)} · step ${d.step}: ${what}` })
        break
      }
      case 'thought':
        steps.push({ t: s.started_at, kind: 'thought', span: s, node: s.node_id!,
          title: `${label(s.node_id)} thinks${d.source === 'think tool' ? ' (think tool)' : ''}: “${clip(d.text, 80)}”` })
        break
      case 'inject':
        steps.push({ t: s.started_at, kind: 'inject', span: s, node: s.node_id!,
          title: `${label(s.node_id)} reads ${d.messages?.length ?? ''} new message(s) mid-turn` })
        break
      case 'tool':
        if (s.name === 'think') break // shown as a 'thought' step
        if (s.ended_at) steps.push({ t: end, kind: 'tool', span: s, node: s.node_id!,
          title: `${label(s.node_id)} · ${s.name}${s.status === 'error' ? ' failed' : ''} → ${clip(d.result, 60)}` })
        break
      case 'message':
        steps.push({ t: s.started_at, kind: 'message', span: s, edge: d.edge_id, node: d.from, target: d.to,
          title: d.kind === 'direct' ? `${label(d.from)} writes to ${label(d.to)}: “${clip(d.content, 60)}”`
            : d.kind === 'post' ? `${label(d.from)} posts to ${label(d.to)}: “${clip(d.content, 60)}”`
            : d.kind === 'board' ? `${label(d.from)} delivers ${d.author ? d.author + '’s ' : ''}post to ${label(d.to)}`
            : `${label(d.from)} → ${label(d.to)} · ${d.kind}` })
        break
      case 'vote':
        steps.push({ t: s.started_at, kind: 'vote', span: s, node: s.node_id!, title: `${s.name} → ${clip(d.winner, 40)}` })
        break
      case 'judge':
        steps.push({ t: end, kind: 'judge', span: s, title: `Judge verdict: ${d.verdict == null ? '?' : d.verdict ? 'correct' : 'incorrect'}` })
        break
      case 'limit': case 'warning':
        steps.push({ t: s.started_at, kind: 'note', span: s, node: s.node_id || undefined, title: s.name })
        break
      case 'run':
        if (s.ended_at) steps.push({ t: end, kind: 'finish', span: s, title: `Run finished${d.answer ? ` — “${clip(d.answer, 60)}”` : ''}` })
        break
    }
  }
  return steps.sort((a, b) => a.t - b.t || PRIORITY[a.kind] - PRIORITY[b.kind] || a.span.started_at - b.span.started_at)
}

function buildSnapshots(steps: Step[], graph: { nodes: any[] }): Snapshot[] {
  const types = Object.fromEntries(graph.nodes.map((n) => [n.id, n.type]))
  let cur: Snapshot = { nodes: {}, edges: {} }
  const ns = (id: string) => (cur.nodes[id] ||= { inbox: 0, stats: emptyStats() })
  const out: Snapshot[] = []
  for (const st of steps) {
    cur = structuredClone(cur)
    const d = st.span.data || {}
    const s = st.span
    if (st.kind === 'start' && st.node) {
      const n = ns(st.node)
      Object.assign(n, { status: 'running', inbox: 0, lastInput: d.input })
      n.stats.activations++
      if (st.edge) { const e = (cur.edges[st.edge] ||= { count: 0 }); e.count++; e.last = d.input }
    } else if (st.kind === 'llm' && st.node && s.status !== 'running') {
      const n = ns(st.node)
      n.stats.llm_calls++
      n.stats.input_tokens += s.input_tokens
      n.stats.output_tokens += s.output_tokens
      n.stats.cached_tokens += d.cached_tokens || 0
      n.stats.cost += s.cost
      if (d.text) n.lastText = d.text
    } else if (st.kind === 'thought' && st.node) {
      const n = ns(st.node)
      n.lastThought = d.text
      if (d.source === 'think tool') n.stats.tool_calls++
    } else if (st.kind === 'inject' && st.node) {
      const n = ns(st.node)
      n.inbox = Math.max(0, n.inbox - (d.messages?.length || 0))
    } else if (st.kind === 'tool' && st.node) {
      const n = ns(st.node)
      n.stats.tool_calls++
      n.lastTool = s.name
    } else if (st.kind === 'end' && st.node) {
      const n = ns(st.node)
      n.status = s.status === 'error' ? 'error' : 'ok'
      n.lastOutput = d.output ?? n.lastOutput
      n.stats.duration_ms += s.duration_ms || 0
      if (s.status === 'error') n.stats.errors++
    } else if (st.kind === 'message') {
      if (st.edge) { const e = (cur.edges[st.edge] ||= { count: 0 }); e.count++; e.last = d.content }
      if (st.node && types[st.node] === 'input') Object.assign(ns(st.node), { status: 'ok', lastOutput: d.content })
      if (st.target) {
        const n = ns(st.target)
        if (types[st.target] === 'output') Object.assign(n, { status: 'ok', lastOutput: d.content })
        else if (types[st.target] === 'board') Object.assign(n, { status: 'ok', posts: (n.posts || 0) + 1, lastOutput: d.content })
        else { n.inbox++; if (n.status !== 'running') n.status = 'waiting' }
      }
    } else if (st.kind === 'vote' && st.node) {
      const n = ns(st.node)
      Object.assign(n, { status: 'ok', inbox: 0, lastOutput: d.winner })
      n.stats.activations++
    }
    out.push(cur)
  }
  return out
}

const SPEEDS = [
  { key: 'slow', label: '1 step / s' },
  { key: 'fast', label: '3 steps / s' },
  { key: 'real', label: 'real time' },
  { key: 'real4', label: 'real ×4' },
]

export default function Replay({ run, models }: { run: Run; models: Record<string, ModelCfg> }) {
  const graph = run.graph_snapshot
  const spans = run.spans || []
  const steps = useMemo(() => (graph ? buildSteps(spans, graph) : []), [spans, graph])
  const snaps = useMemo(() => (graph ? buildSnapshots(steps, graph) : []), [steps, graph])
  const [cur, setCur] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState('slow')
  const [pinned, setPinned] = useState<string | null>(null)
  const [hoverNode, setHoverNode] = useState<string | null>(null)
  const [hoverEdge, setHoverEdge] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const prevLen = useRef(0)
  useEffect(() => markFlag('ac.replaySeen'), [])

  // Start at the end for finished runs; follow new steps of a live run if the user is at the end.
  useEffect(() => {
    if (prevLen.current === 0 || cur >= prevLen.current - 1) setCur(Math.max(steps.length - 1, 0))
    prevLen.current = steps.length
  }, [steps.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const last = steps.length - 1
  const go = (i: number) => setCur(Math.max(0, Math.min(last, i)))

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) && (el as HTMLInputElement).type !== 'range') return
      if (e.key === 'ArrowRight') { setPlaying(false); setCur((c) => Math.min(last, c + 1)); e.preventDefault() }
      else if (e.key === 'ArrowLeft') { setPlaying(false); setCur((c) => Math.max(0, c - 1)); e.preventDefault() }
      else if (e.key === 'Home') { setCur(0); e.preventDefault() }
      else if (e.key === 'End') { setCur(last); e.preventDefault() }
      else if (e.key === ' ') { setPlaying((p) => !p); e.preventDefault() }
      else if (e.key === 'Escape') setPinned(null)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [last])

  useEffect(() => {
    if (!playing) return
    if (cur >= last) { setPlaying(false); return }
    const gap = (steps[cur + 1].t - steps[cur].t) * 1000
    const delay = speed === 'slow' ? 1000 : speed === 'fast' ? 330
      : Math.min(Math.max(gap / (speed === 'real4' ? 4 : 1), 120), 3000)
    const timer = window.setTimeout(() => setCur((c) => c + 1), delay)
    return () => window.clearTimeout(timer)
  }, [playing, cur, last, speed, steps])

  useEffect(() => {
    listRef.current?.querySelector('.step.cur')?.scrollIntoView({ block: 'nearest' })
  }, [cur])

  if (!graph) return <div className="empty">Graph snapshot not available.</div>
  if (!steps.length) return <div className="empty">No steps yet.</div>

  const step = steps[cur]
  const snap = snaps[cur]
  const t0 = steps[0].t
  const nodes = graph.nodes.map((n: any) => {
    const st = snap.nodes[n.id]
    const focus = step.node === n.id || (step.kind === 'message' && step.target === n.id)
    return {
      ...n, draggable: false, selected: pinned === n.id,
      data: { ...n.data, _models: models, _status: st?.status, _stats: st?.stats.activations ? st.stats : undefined,
        _inbox: st?.inbox, _focus: focus, _dim: !st?.status && !focus, _posts: st?.posts, _lastPost: n.type === 'board' ? clip(st?.lastOutput, 40) : undefined },
    }
  })
  const names = Object.fromEntries(graph.nodes.map((n: any) => [n.id, n.data?.label || n.id]))
  const edges = graph.edges.map((e: any) => {
    const es = snap.edges[e.id]
    return styleEdge(e, { active: step.edge === e.id, dim: !es?.count && step.edge !== e.id, count: es?.count, names })
  })
  const inspectNode = hoverNode || pinned
  const inspectEdge = !inspectNode ? hoverEdge : null

  return (
    <div className="replay">
      <div>
        <div className="card replay-canvas">
          <div className="replay-caption"><div><b>{cur + 1}.</b> {step.title}</div></div>
          <ReactFlowProvider>
            <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} colorMode="system" fitView fitViewOptions={{ padding: 0.3 }}
              nodesConnectable={false} nodesDraggable={false} edgesFocusable={false}
              onNodeClick={(_, n) => setPinned((p) => (p === n.id ? null : n.id))} onPaneClick={() => setPinned(null)}
              onNodeMouseEnter={(_, n) => setHoverNode(n.id)} onNodeMouseLeave={() => setHoverNode(null)}
              onEdgeMouseEnter={(_, e) => setHoverEdge(e.id)} onEdgeMouseLeave={() => setHoverEdge(null)}>
              <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
              <Controls showInteractive={false} position="bottom-right" />
            </ReactFlow>
          </ReactFlowProvider>
        </div>
        <div className="card" style={{ padding: 0, marginTop: 8 }}>
          <div className="replay-bar" style={{ borderTop: 'none' }}>
            <button className="sm" title="First step (Home)" onClick={() => go(0)}>⏮</button>
            <button className="sm" title="Previous step (←)" onClick={() => { setPlaying(false); go(cur - 1) }}>◀</button>
            <button className="sm primary" title="Play / pause (Space)" style={{ minWidth: 34, justifyContent: 'center' }}
              onClick={() => { if (cur >= last) setCur(0); setPlaying(!playing) }}>{playing ? '❚❚' : '▶'}</button>
            <button className="sm" title="Next step (→)" onClick={() => { setPlaying(false); go(cur + 1) }}>▶</button>
            <button className="sm" title="Last step (End)" onClick={() => go(last)}>⏭</button>
            <input type="range" min={0} max={last} value={cur} onChange={(e) => { setPlaying(false); setCur(+e.target.value) }} />
            <span className="counter">{cur + 1} / {steps.length}</span>
            <select value={speed} onChange={(e) => setSpeed(e.target.value)} style={{ width: 110, padding: '3px 6px', fontSize: 12 }}>
              {SPEEDS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <Tip text={HINTS.replay} />
          </div>
          <div className="steps" ref={listRef}>
            {steps.map((s, i) => (
              <div key={i} className={`step ${i === cur ? 'cur' : i > cur ? 'future' : ''}`} onClick={() => { setPlaying(false); setCur(i) }}>
                <span className="mono faint">{i + 1}</span>
                <span className="mono muted">+{fmtMs((s.t - t0) * 1000)}</span>
                <span className="k">{s.kind}</span>
                <span className="clip" style={{ maxWidth: '100%' }}>{s.title}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="small muted" style={{ marginTop: 6 }}>
          <kbd>←</kbd> <kbd>→</kbd> step · <kbd>Space</kbd> play · <kbd>Home</kbd>/<kbd>End</kbd> · hover a node or edge to inspect it, click a node to pin
        </div>
      </div>

      <div className="detail">
        {inspectNode && <NodePanel id={inspectNode} graph={graph} st={snap.nodes[inspectNode]} pinned={pinned === inspectNode} />}
        {inspectEdge && <EdgePanel id={inspectEdge} graph={graph} st={snap.edges[inspectEdge]} />}
        <div className="row"><span className="pill">{step.kind}</span><span className="mono small muted">step {cur + 1} · +{fmtMs((step.t - t0) * 1000)}</span></div>
        <SpanDetail s={step.span} spans={spans} />
      </div>
    </div>
  )
}

function NodePanel({ id, graph, st, pinned }: { id: string; graph: { nodes: any[] }; st?: NodeState; pinned: boolean }) {
  const n = graph.nodes.find((x) => x.id === id)
  const s = st?.stats
  return (
    <div className="card col" style={{ background: 'var(--soft)', borderColor: 'var(--line-2)' }}>
      <div className="row">
        <h3 style={{ margin: 0 }}>{n?.data?.label || id}</h3><span className="mono small faint">{n?.type}</span>
        <Pill status={st?.status || 'idle'} />{pinned && <span className="small muted">pinned · Esc to unpin</span>}
      </div>
      <div className="kv">
        <div>Activations</div><div className="mono">{s?.activations ?? 0}</div>
        <div>LLM / tools</div><div className="mono">{s?.llm_calls ?? 0} / {s?.tool_calls ?? 0}{st?.lastTool ? ` · last ${st.lastTool}` : ''}</div>
        <div>Tokens so far</div><div className="mono">{fmtTok(s?.input_tokens ?? 0)} in · {fmtTok(s?.output_tokens ?? 0)} out{s?.cached_tokens ? ` · ${fmtTok(s.cached_tokens)} cached` : ''}</div>
        <div>Cost so far</div><div className="mono">{fmtCost(s?.cost ?? 0)}</div>
        <div>Busy time</div><div className="mono">{fmtMs(s?.duration_ms ?? 0)}</div>
        {!!st?.inbox && <><div>Inbox</div><div className="mono c-orange">{fmtNum(st.inbox)} unprocessed</div></>}
        {!!st?.posts && <><div>Posts</div><div className="mono">{st.posts}</div></>}
      </div>
      {st?.lastInput && <div className="block"><div className="bh">Last input</div><div className="bb" style={{ maxHeight: 160 }}><pre>{st.lastInput}</pre></div></div>}
      {st?.lastThought && <div className="block"><div className="bh">Last thought</div><div className="bb" style={{ maxHeight: 140 }}><pre className="muted">{st.lastThought}</pre></div></div>}
      {st?.lastText && st.lastText !== st.lastOutput && <div className="block"><div className="bh">Last model text</div><div className="bb" style={{ maxHeight: 140 }}><pre>{st.lastText}</pre></div></div>}
      {st?.lastOutput && <div className="block"><div className="bh">Last output</div><div className="bb" style={{ maxHeight: 160 }}><pre>{st.lastOutput}</pre></div></div>}
      {!st && <span className="small muted">Not reached yet at this step.</span>}
    </div>
  )
}

function EdgePanel({ id, graph, st }: { id: string; graph: { nodes: any[]; edges: any[] }; st?: EdgeState }) {
  const e = graph.edges.find((x) => x.id === id)
  const label = (nid: string) => graph.nodes.find((n) => n.id === nid)?.data?.label || nid
  if (!e) return null
  return (
    <div className="card col" style={{ background: 'var(--soft)', borderColor: 'var(--line-2)' }}>
      <div className="row"><h3 style={{ margin: 0 }}>{label(e.source)} → {label(e.target)}</h3><span className="pill">{e.data?.kind || 'flow'}</span></div>
      <span className="small mono">{st?.count ? `fired ${st.count}×` : 'not fired yet'}</span>
      {st?.last && <div className="block"><div className="bh">Last payload</div><div className="bb" style={{ maxHeight: 160 }}><pre>{st.last}</pre></div></div>}
    </div>
  )
}
