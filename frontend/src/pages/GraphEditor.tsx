import {
  Background, BackgroundVariant, Connection, Controls, Edge, MiniMap, Node, ReactFlow, ReactFlowProvider,
  addEdge, useEdgesState, useNodesState, useReactFlow,
} from '@xyflow/react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Dataset, EdgeKind, GraphData, GraphRow, Meta, ModelCfg, Run, api } from '../api'
import { EDGE_KINDS, EdgeLegend, nodeTypes, styleEdge } from '../flow'
import { HINTS } from '../hints'
import TemplateGallery from '../Templates'
import { Mark, Modal, Pill, Tip, fmtCost, fmtMs, fmtTok, go, usePoll, useToast } from '../ui'
import { nodeStatuses } from './RunView'

const uid = (p: string) => p + Math.random().toString(36).slice(2, 8)

const DEFAULT_SETTINGS = {
  max_activations: 40, timeout_s: 900, keep_workspace: true,
  sandbox: { type: 'docker', image: 'python:3.12-slim', network: false, timeout: 60 },
}

function blankGraph(modelId?: string): GraphData {
  return {
    nodes: [
      { id: 'in', type: 'input', position: { x: 0, y: 120 }, data: { label: 'Task' } },
      { id: uid('a_'), type: 'agent', position: { x: 240, y: 90 }, data: {
        label: 'Agent', model_id: modelId, system_prompt: 'You are a careful problem solver. End with <answer>…</answer>.',
        tools: ['shell', 'read_file', 'write_file', 'edit_file', 'list_dir', 'search'], max_steps: 15,
        memory: 'persistent', join: 'all', include_task: true } },
      { id: 'out', type: 'output', position: { x: 540, y: 120 }, data: { label: 'Answer' } },
    ],
    edges: [],
    settings: DEFAULT_SETTINGS,
  }
}

const strip = (n: Node) => {
  const { _status, _stats, _models, ...data } = n.data as any
  return { id: n.id, type: n.type, position: n.position, data }
}

export default function GraphEditorPage({ id }: { id?: string }) {
  return <ReactFlowProvider><GraphEditor id={id} /></ReactFlowProvider>
}

function GraphEditor({ id }: { id?: string }) {
  const toast = useToast()
  const rf = useReactFlow()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [models, setModels] = useState<ModelCfg[]>([])
  const [graphs, setGraphs] = useState<GraphRow[]>([])
  const [name, setName] = useState('')
  const [settings, setSettings] = useState<any>(DEFAULT_SETTINGS)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [dirty, setDirty] = useState(false)
  const [connectKind, setConnectKind] = useState<EdgeKind>('flow')
  const [modal, setModal] = useState<'run' | 'eval' | 'new' | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [checks, setChecks] = useState<{ ok: boolean; errors: string[]; warnings: string[] } | null>(null)

  useEffect(() => {
    api.meta().then(setMeta)
    api.models().then(setModels)
    api.graphs().then((gs) => {
      setGraphs(gs)
      if (!id && gs.length) go(`graphs/${gs[0].id}`)
    })
  }, [id])

  useEffect(() => {
    if (!id) return
    setRunId(null)
    api.graph(id).then((g) => {
      setName(g.name)
      setNodes(g.data.nodes || [])
      setEdges(g.data.edges || [])
      setSettings({ ...DEFAULT_SETTINGS, ...(g.data.settings || {}) })
      setDirty(false)
      window.setTimeout(() => rf.fitView({ padding: 0.25 }), 50)
    }).catch((e) => toast(e.message, true))
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  const modelMap = useMemo(() => Object.fromEntries(models.map((m) => [m.id, m])), [models])
  const run = usePoll<Run | null>(() => (runId ? api.run(runId) : Promise.resolve(null)), [runId], 700,
    (r) => !!r && ['queued', 'running'].includes(r.status))
  const statuses = useMemo(() => (run.data ? nodeStatuses(run.data) : {}), [run.data])

  const viewNodes = useMemo(() => nodes.map((n) => ({
    ...n, data: { ...n.data, _models: modelMap, _status: statuses[n.id], _stats: run.data?.node_stats?.[n.id] },
  })), [nodes, modelMap, statuses, run.data])
  const names = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, (n.data as any)?.label || n.id])), [nodes])
  const viewEdges = useMemo(() => edges.map((e) => styleEdge(e, { active: statuses[e.target] === 'running', names })), [edges, statuses, names])

  const selectedNode = nodes.find((n) => n.selected)
  const selectedEdge = edges.find((e) => e.selected)
  const touch = () => setDirty(true)

  // Live static checks of the graph (missing model, wrong link endpoints, unreachable nodes…).
  useEffect(() => {
    if (!id || !nodes.length) return
    const t = window.setTimeout(() => {
      api.validateGraph(name || 'graph', data()).then(setChecks).catch(() => setChecks(null))
    }, 400)
    return () => window.clearTimeout(t)
  }, [nodes, edges, settings, models]) // eslint-disable-line react-hooks/exhaustive-deps

  const onConnect = useCallback((c: Connection) => {
    setEdges((es) => addEdge({ ...c, id: uid('e_'), data: { kind: connectKind, max_iterations: 3 } }, es))
    setDirty(true)
  }, [connectKind, setEdges])

  const addNode = (type: string) => {
    const center = rf.screenToFlowPosition({ x: window.innerWidth / 2 - 100, y: window.innerHeight / 2 - 60 })
    const base: any = { label: { agent: 'Agent', vote: 'Vote', input: 'Task', output: 'Answer', board: 'Board' }[type] }
    if (type === 'agent') Object.assign(base, {
      model_id: models[0]?.id, system_prompt: '', tools: meta?.default_tools || [], max_steps: 15,
      memory: 'persistent', join: 'all', include_task: true,
    })
    const n: Node = { id: uid(type[0] + '_'), type, position: { x: center.x + Math.random() * 40, y: center.y + Math.random() * 40 }, data: base, selected: true }
    setNodes((ns) => [...ns.map((x) => ({ ...x, selected: false })), n])
    touch()
  }

  const patchNode = (nid: string, patch: Record<string, any>) => {
    setNodes((ns) => ns.map((n) => (n.id === nid ? { ...n, data: { ...n.data, ...patch } } : n)))
    touch()
  }
  const patchEdge = (eid: string, patch: Record<string, any>) => {
    setEdges((es) => es.map((e) => (e.id === eid ? { ...e, data: { ...(e.data || {}), ...patch } } : e)))
    touch()
  }

  const data = (): GraphData => ({ nodes: nodes.map(strip), edges: edges.map(({ id, source, target, sourceHandle, targetHandle, data }) => ({ id, source, target, sourceHandle, targetHandle, data })), settings })

  const save = async () => {
    if (!id) return
    try {
      await api.updateGraph(id, name || 'Untitled', data())
      setDirty(false)
      setGraphs(await api.graphs())
      toast('Saved')
      return true
    } catch (e: any) { toast(e.message, true); return false }
  }

  const create = async (copy = false) => {
    const g = await api.createGraph(copy ? `${name} (copy)` : 'New graph', copy ? data() : blankGraph(models[0]?.id))
    go(`graphs/${g.id}`)
  }

  const remove = async () => {
    if (!id || !confirm(`Delete graph "${name}"?`)) return
    await api.deleteGraph(id)
    const gs = await api.graphs()
    setGraphs(gs)
    go(gs.length ? `graphs/${gs[0].id}` : 'graphs')
  }

  if (!id) {
    return (
      <div className="page"><div className="empty">
        <p>No graphs yet.</p><button className="primary" onClick={() => setModal('new')}>Create graph</button>
        {modal === 'new' && <TemplateGallery models={models} onClose={() => setModal(null)} onBlank={() => create()} />}
      </div></div>
    )
  }

  return (
    <div className="editor">
      <div className="editor-main">
        <div className="toolbar">
          <select value={id} onChange={(e) => go(`graphs/${e.target.value}`)} style={{ width: 200 }}>
            {graphs.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <input className="name" value={name} onChange={(e) => { setName(e.target.value); touch() }} />
          <button className={dirty ? 'primary' : ''} onClick={save} disabled={!dirty}>{dirty ? 'Save' : 'Saved'}</button>
          {checks && (checks.errors.length > 0 || checks.warnings.length > 0) && (
            <button className="ghost" title="Show graph checks" onClick={() => { setNodes((ns) => ns.map((n) => ({ ...n, selected: false }))); setEdges((es) => es.map((e) => ({ ...e, selected: false }))) }}>
              {checks.errors.length > 0 && <span className="c-red">● {checks.errors.length}</span>}
              {checks.warnings.length > 0 && <span className="c-orange">● {checks.warnings.length}</span>}
            </button>
          )}
          <button className="ghost" title="New graph from a typical architecture or blank" onClick={() => setModal('new')}>New</button>
          <button className="ghost" onClick={() => create(true)}>Duplicate</button>
          <button className="ghost danger" onClick={remove}>Delete</button>
          <span className="spacer" />
          <span className="small muted">connect as</span><Tip text={HINTS.connectAs} />
          <div className="seg">
            {EDGE_KINDS.map((k) => (
              <button key={k.kind} className={connectKind === k.kind ? 'on' : ''} title={k.hint} onClick={() => setConnectKind(k.kind)}>{k.label}</button>
            ))}
          </div>
          <button title="Run once on a task you type" onClick={async () => { if (!dirty || await save()) setModal('run') }}>▶ Run</button>
          <button className="primary" onClick={async () => { if (!dirty || await save()) setModal('eval') }}>Evaluate on dataset</button><Tip text={HINTS.evaluate} />
        </div>
        <div className="canvas">
          <div className="palette">
            <div className="lbl">Add <Tip text={HINTS.palette} /></div>
            <button onClick={() => addNode('agent')}>＋ Agent</button>
            <button onClick={() => addNode('vote')}>＋ Vote</button>
            <button onClick={() => addNode('board')}>＋ Board</button>
            <button onClick={() => addNode('input')}>＋ Input</button>
            <button onClick={() => addNode('output')}>＋ Output</button>
          </div>
          <ReactFlow
            nodes={viewNodes} edges={viewEdges} nodeTypes={nodeTypes}
            onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type !== 'select' && x.type !== 'dimensions')) touch() }}
            onEdgesChange={(c) => { onEdgesChange(c); if (c.some((x) => x.type !== 'select')) touch() }}
            colorMode="system" onConnect={onConnect} deleteKeyCode={['Delete', 'Backspace']} fitView minZoom={0.2}
          >
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable style={{ width: 140, height: 90 }} />
          </ReactFlow>
          <EdgeLegend />
          {!nodes.some((n) => n.type === 'agent') && (
            <div className="canvas-empty"><div><b>Пустой граф.</b> Добавьте Input, один или несколько Agent и Output через панель слева, затем соедините их стрелками: от правой точки узла к левой точке следующего.</div></div>
          )}
        </div>
        {runId && run.data && <RunDrawer run={run.data} onClose={() => setRunId(null)} />}
      </div>

      <aside className="inspector">
        {selectedNode ? (
          <NodeInspector node={selectedNode} meta={meta} models={models} edges={edges} nodes={nodes}
            onChange={(p) => patchNode(selectedNode.id, p)}
            onDelete={() => { setNodes((ns) => ns.filter((n) => n.id !== selectedNode.id)); setEdges((es) => es.filter((e) => e.source !== selectedNode.id && e.target !== selectedNode.id)); touch() }} />
        ) : selectedEdge ? (
          <EdgeInspector edge={selectedEdge} nodes={nodes} edges={edges} onChange={(p) => patchEdge(selectedEdge.id, p)}
            onDelete={() => { setEdges((es) => es.filter((e) => e.id !== selectedEdge.id)); touch() }} />
        ) : (
          <GraphSettings settings={settings} checks={checks} docker={meta?.docker} dockerDetail={meta?.docker_detail} onChange={(s) => { setSettings(s); touch() }} />
        )}
      </aside>

      {modal === 'run' && <RunModal graphId={id} onClose={() => setModal(null)} onStarted={(rid) => { setRunId(rid); setModal(null) }} />}
      {modal === 'new' && <TemplateGallery models={models} onClose={() => setModal(null)} onBlank={() => create()} />}
      {modal === 'eval' && <EvalModal graphId={id} graphName={name} models={models} onClose={() => setModal(null)} />}
    </div>
  )
}

// ---- inspectors -----------------------------------------------------------------------------

function NodeInspector({ node, meta, models, edges, nodes, onChange, onDelete }: {
  node: Node; meta: Meta | null; models: ModelCfg[]; edges: Edge[]; nodes: Node[]
  onChange: (p: Record<string, any>) => void; onDelete: () => void
}) {
  const d: any = node.data
  const generated = generatedTools(node, nodes, edges)
  const tools: string[] = d.tools || []
  return (
    <>
      <h3>{node.type === 'agent' ? 'Agent' : node.type?.[0].toUpperCase() + node.type!.slice(1)}<span className="spacer" />
        <button className="sm danger" onClick={onDelete}>Delete</button></h3>
      <label className="field">Label<input value={d.label || ''} onChange={(e) => onChange({ label: e.target.value })} /></label>
      {node.type === 'agent' && (
        <>
          <label className="field"><span>Model<Tip text={HINTS.model} /></span>
            <select value={d.model_id || ''} onChange={(e) => onChange({ model_id: e.target.value })}>
              <option value="">— select —</option>
              {models.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.provider}/{m.model}</option>)}
            </select>
            {!models.length && <span className="hint">Add a model on the Models page first.</span>}
          </label>
          <label className="field"><span>System prompt<Tip text={HINTS.systemPrompt} /></span>
            <textarea rows={8} value={d.system_prompt || ''} onChange={(e) => onChange({ system_prompt: e.target.value })} />
          </label>
          <div className="field" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span className="small muted" style={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 500 }}>Tools<Tip text={HINTS.tools} /></span>
            <div className="tools-grid">
              {meta?.tools.map((t) => (
                <label key={t.name} className="check" title={t.description}>
                  <input type="checkbox" checked={tools.includes(t.name)}
                    onChange={(e) => onChange({ tools: e.target.checked ? [...tools, t.name] : tools.filter((x) => x !== t.name) })} />
                  <span className="mono">{t.name}</span>
                </label>
              ))}
            </div>
            {generated.length > 0 && <span className="small muted">From connections<Tip text={HINTS.generatedTools} />:</span>}
            {generated.map((g) => (
              <span key={g.name} className="small muted">+ <span className="mono">{g.name}</span>{g.note ? ` — ${g.note}` : ''}</span>
            ))}
          </div>
          <div className="grid2">
            <label className="field"><span>Max steps<Tip text={HINTS.maxSteps} /></span><input type="number" min={1} value={d.max_steps ?? 15} onChange={(e) => onChange({ max_steps: +e.target.value })} /></label>
            <label className="field"><span>Max tokens<Tip text={HINTS.maxTokens} /></span><input type="number" min={256} placeholder="16000" value={d.max_tokens ?? ''} onChange={(e) => onChange({ max_tokens: e.target.value ? +e.target.value : null })} /></label>
            <label className="field"><span>Effort<Tip text={HINTS.effort} /></span>
              <select value={d.effort || ''} onChange={(e) => onChange({ effort: e.target.value || null })}>
                <option value="">default</option>{['low', 'medium', 'high', 'xhigh', 'max'].map((x) => <option key={x}>{x}</option>)}
              </select>
            </label>
            <label className="field"><span>Temperature<Tip text={HINTS.temperature} /></span><input placeholder="default" value={d.temperature ?? ''} onChange={(e) => onChange({ temperature: e.target.value === '' ? null : +e.target.value })} /></label>
            <label className="field"><span>Memory<Tip text={HINTS.memory} /></span>
              <select value={d.memory || 'persistent'} onChange={(e) => onChange({ memory: e.target.value })}>
                <option value="persistent">persistent</option><option value="fresh">fresh each activation</option>
              </select>
            </label>
            <label className="field"><span>Join<Tip text={HINTS.join} /></span>
              <select value={d.join || 'all'} onChange={(e) => onChange({ join: e.target.value })}>
                <option value="all">wait for all inputs</option><option value="any">fire on each input</option>
              </select>
            </label>
          </div>
          <label className="check"><input type="checkbox" checked={d.include_task !== false} onChange={(e) => onChange({ include_task: e.target.checked })} />Include original task in first prompt<Tip text={HINTS.includeTask} /></label>
          <label className="check"><input type="checkbox" checked={d.auto_context !== false} onChange={(e) => onChange({ auto_context: e.target.checked })} />Append role/collaboration context to system prompt<Tip text={HINTS.autoContext} /></label>
          <span className="hint">Temperature is rejected by recent Anthropic models — leave empty unless the model accepts it.</span>
        </>
      )}
      {node.type === 'board' && <span className="small muted">A shared message board. Agents with a Message link to it get <code>post_…</code>; agents with a Subscribe link receive every post as a new message. Everyone connected can read it with <code>read_…</code>.<Tip text={HINTS.board} /></span>}
      {node.type === 'vote' && <span className="small muted">Collects all incoming answers, extracts <code>&lt;answer&gt;</code> (or a final line) and emits the most common one.</span>}
      {node.type === 'output' && <span className="small muted">The last message delivered here is the run's answer and is scored against the dataset reference.</span>}
      {node.type === 'input' && <span className="small muted">Emits the task text when the run starts.</span>}
    </>
  )
}

const slug = (s: string) => s.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'agent'

/** Tools the engine adds to an agent because of its connections (mirrors backend graph.py). */
function generatedTools(node: Node, nodes: Node[], edges: Edge[]): { name: string; note?: string }[] {
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const lbl = (id: string) => (byId[id]?.data as any)?.label || id
  const out: { name: string; note?: string }[] = []
  const posts = new Set<string>(), subs = new Set<string>()
  const filtered = new Map<string, string[]>(), unfiltered = new Set<string>()
  for (const e of edges) {
    const d: any = e.data || {}
    const kind = d.kind || 'flow'
    const mine = e.source === node.id, theirs = e.target === node.id
    if (!mine && !theirs) continue
    const other = mine ? e.target : e.source
    const otherType = byId[other]?.type
    if (mine && kind === 'handoff') out.push({ name: `handoff_to_${slug(lbl(other))}`, note: 'ends the turn' })
    if (mine && kind === 'delegate') out.push({ name: `ask_${slug(lbl(other))}`, note: 'runs it as a sub-agent' })
    if (kind === 'message' && (mine || d.bidirectional)) {
      if (otherType === 'agent') out.push({ name: `message_${slug(lbl(other))}` })
      if (otherType === 'board') posts.add(other)
    }
    if (kind === 'message' && otherType === 'board' && (theirs || d.bidirectional)) { subs.add(other); unfiltered.add(other) }
    if (kind === 'flow' && theirs && otherType === 'board') { subs.add(other); unfiltered.add(other) }
    if (kind === 'subscribe' && otherType === 'board') {
      subs.add(other)
      if (d.authors?.length) filtered.set(other, [...(filtered.get(other) || []), ...d.authors.map(lbl)])
      else unfiltered.add(other)
    }
  }
  posts.forEach((b) => out.push({ name: `post_${slug(lbl(b))}` }))
  const receives = (b: string) => !subs.has(b) ? undefined
    : unfiltered.has(b) ? 'and receives its posts' : `and receives posts by ${[...new Set(filtered.get(b))].join(', ')}`
  new Set([...posts, ...subs]).forEach((b) => out.push({ name: `read_${slug(lbl(b))}`, note: receives(b) }))
  return out
}

/** Nodes that can publish to a board — mirrors `_posters` in backend/app/engine/validate.py. */
function boardPosters(board: string, nodes: Node[], edges: Edge[]): string[] {
  const type = (id: string) => nodes.find((n) => n.id === id)?.type
  const out = new Set<string>()
  for (const e of edges) {
    const d: any = e.data || {}
    const kind = d.kind || 'flow'
    if (['flow', 'conditional', 'feedback', 'message'].includes(kind) && e.target === board) out.add(e.source)
    else if (kind === 'message' && e.source === board && d.bidirectional && type(e.target) === 'agent') out.add(e.target)
  }
  return [...out]
}

function AuthorPicker({ edge, nodes, edges, onChange }: { edge: Edge; nodes: Node[]; edges: Edge[]; onChange: (p: any) => void }) {
  const d: any = edge.data || {}
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const board = byId[edge.target]?.type === 'board' ? edge.target : byId[edge.source]?.type === 'board' ? edge.source : null
  if (!board) return null
  const subscriber = board === edge.target ? edge.source : edge.target
  const authors: string[] = d.authors || []
  const posters = boardPosters(board, nodes, edges).filter((id) => id !== subscriber)
  // Every agent is offered (posters first), so a filter can be set before the posting edges are drawn.
  const others = nodes.filter((n) => n.type === 'agent' && n.id !== subscriber && !posters.includes(n.id)).map((n) => n.id)
  const candidates = [...posters, ...others, ...authors.filter((a) => !posters.includes(a) && !others.includes(a))]
  const toggle = (id: string) => onChange({ authors: authors.includes(id) ? authors.filter((a) => a !== id) : [...authors, id] })
  const name = (id: string) => (byId[id]?.data as any)?.label || id
  return (
    <div className="field">
      <span>Receive posts from<Tip text={HINTS.subscribeAuthors} /></span>
      <label className="check"><input type="checkbox" checked={!authors.length} onChange={() => onChange({ authors: [] })} />everyone</label>
      {candidates.map((id) => (
        <label key={id} className="check">
          <input type="checkbox" checked={authors.includes(id)} onChange={() => toggle(id)} />
          {name(id)}{!byId[id] ? <span className="small" style={{ color: 'var(--red)' }}>&nbsp;· deleted</span>
            : !posters.includes(id) && <span className="small faint">&nbsp;· cannot post here yet</span>}
        </label>
      ))}
    </div>
  )
}

function EdgeInspector({ edge, nodes, edges, onChange, onDelete }: { edge: Edge; nodes: Node[]; edges: Edge[]; onChange: (p: any) => void; onDelete: () => void }) {
  const d: any = edge.data || {}
  const kind: EdgeKind = d.kind || 'flow'
  const label = (nid: string) => (nodes.find((n) => n.id === nid)?.data as any)?.label || nid
  const cond = d.condition || { type: kind === 'feedback' ? 'not_contains' : 'contains', value: '' }
  return (
    <>
      <h3>Connection<span className="spacer" /><button className="sm danger" onClick={onDelete}>Delete</button></h3>
      <div className="small muted">{label(edge.source)} → {label(edge.target)}</div>
      <label className="field"><span>Kind<Tip text={HINTS.edgeKind} /></span>
        <select value={kind} onChange={(e) => onChange({ kind: e.target.value })}>
          {EDGE_KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
        </select>
        <span className="hint">{EDGE_KINDS.find((k) => k.kind === kind)?.hint}</span>
      </label>
      {(kind === 'conditional' || kind === 'feedback') && (
        <div className="grid2">
          <label className="field"><span>Condition<Tip text={HINTS.condition} /></span>
            <select value={cond.type} onChange={(e) => onChange({ condition: { ...cond, type: e.target.value } })}>
              <option value="always">always</option><option value="contains">contains</option>
              <option value="not_contains">not contains</option><option value="regex">regex</option>
            </select>
          </label>
          <label className="field">Value<input value={cond.value || ''} onChange={(e) => onChange({ condition: { ...cond, value: e.target.value } })} /></label>
        </div>
      )}
      {kind === 'feedback' && (
        <label className="field"><span>Max iterations<Tip text={HINTS.maxIterations} /></span><input type="number" min={1} value={d.max_iterations ?? 3} onChange={(e) => onChange({ max_iterations: +e.target.value })} /></label>
      )}
      {kind === 'message' && (
        <label className="check"><input type="checkbox" checked={!!d.bidirectional} onChange={(e) => onChange({ bidirectional: e.target.checked })} />Two-way: {label(edge.target)} can write back<Tip text={HINTS.bidirectional} /></label>
      )}
      {kind === 'subscribe' && <span className="small muted">Connect an agent and a board (either direction). The agent receives new posts of the board as messages — while working, before its next model call; when idle, it gets activated.<Tip text={HINTS.subscribe} /></span>}
      {kind === 'subscribe' && <AuthorPicker edge={edge} nodes={nodes} edges={edges} onChange={onChange} />}
      {(kind === 'handoff' || kind === 'delegate' || kind === 'message') && (
        <label className="field"><span>Tool description<Tip text={HINTS.toolDescription} /></span><textarea rows={3} value={d.label || ''} placeholder="When should the agent use this?" onChange={(e) => onChange({ label: e.target.value })} /></label>
      )}
    </>
  )
}

function GraphSettings({ settings, checks, docker, dockerDetail, onChange }: {
  settings: any; checks: { errors: string[]; warnings: string[] } | null; docker?: boolean; dockerDetail?: string; onChange: (s: any) => void
}) {
  const sb = settings.sandbox || {}
  const set = (p: any) => onChange({ ...settings, ...p })
  const setSb = (p: any) => onChange({ ...settings, sandbox: { ...sb, ...p } })
  return (
    <>
      <h3>Graph settings</h3>
      <span className="small muted">Select a node or connection to edit it. Drag from a handle to connect; the kind is set by “connect as”.</span>
      {checks && (
        <div className="checks">
          {checks.errors.map((m) => <span key={m} className="e">● {m}</span>)}
          {checks.warnings.map((m) => <span key={m} className="w">● {m}</span>)}
          {!checks.errors.length && !checks.warnings.length && <span className="c-green">● Graph looks valid</span>}
        </div>
      )}
      <div className="divider" />
      <label className="field"><span>Sandbox<Tip text={HINTS.sandbox} /></span>
        <select value={sb.type || 'docker'} onChange={(e) => setSb({ type: e.target.value })}>
          <option value="docker">Docker container (isolated)</option>
          <option value="local">Local process (not isolated)</option>
        </select>
        {sb.type !== 'local' && docker === false && <span className="hint c-red">{dockerDetail} — runs will fail until Docker is available.</span>}
        {sb.type !== 'local' && docker && <span className="hint c-green">{dockerDetail} ready</span>}
        {sb.type === 'local' && <span className="hint c-orange">Shell commands run on your machine inside the workspace dir.</span>}
      </label>
      {sb.type !== 'local' && (
        <>
          <label className="field">Image<input value={sb.image || ''} onChange={(e) => setSb({ image: e.target.value })} /></label>
          <div className="grid2">
            <label className="field">Memory<input value={sb.memory || '1g'} onChange={(e) => setSb({ memory: e.target.value })} /></label>
            <label className="field">CPUs<input type="number" step={0.5} value={sb.cpus ?? 1} onChange={(e) => setSb({ cpus: +e.target.value })} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={!!sb.network} onChange={(e) => setSb({ network: e.target.checked })} />Network access<Tip text={HINTS.network} /></label>
        </>
      )}
      <label className="field">Command timeout, s<input type="number" value={sb.timeout ?? 60} onChange={(e) => setSb({ timeout: +e.target.value })} /></label>
      <label className="field"><span>Setup command<Tip text={HINTS.setup} /></span><input placeholder="e.g. pip install -q numpy" value={settings.setup_command || ''} onChange={(e) => set({ setup_command: e.target.value })} />
        <span className="hint">Runs in the sandbox before each task (datasets can override with a <code>setup</code> field).</span></label>
      <div className="divider" />
      <div className="grid2">
        <label className="field"><span>Max activations<Tip text={HINTS.maxActivations} /></span><input type="number" value={settings.max_activations ?? 40} onChange={(e) => set({ max_activations: +e.target.value })} /></label>
        <label className="field"><span>Run timeout, s<Tip text={HINTS.runTimeout} /></span><input type="number" value={settings.timeout_s ?? 900} onChange={(e) => set({ timeout_s: +e.target.value })} /></label>
      </div>
      <label className="check"><input type="checkbox" checked={settings.keep_workspace !== false} onChange={(e) => set({ keep_workspace: e.target.checked })} />Keep workspace files after run</label>
    </>
  )
}

// ---- run / evaluate -----------------------------------------------------------------------

function RunModal({ graphId, onClose, onStarted }: { graphId: string; onClose: () => void; onStarted: (id: string) => void }) {
  const toast = useToast()
  const [task, setTask] = useState('')
  const [expected, setExpected] = useState('')
  const start = async () => {
    try {
      const r = await api.startRun({ graph_id: graphId, task, expected: expected || null })
      onStarted(r.id)
    } catch (e: any) { toast(e.message, true) }
  }
  return (
    <Modal title="Run graph on a task" onClose={onClose}>
      <label className="field">Task<textarea rows={7} autoFocus value={task} onChange={(e) => setTask(e.target.value)} /></label>
      <label className="field">Expected answer <span className="hint">optional — scored with the auto scorer</span><input value={expected} onChange={(e) => setExpected(e.target.value)} /></label>
      <div className="row"><span className="spacer" /><button onClick={onClose}>Cancel</button><button className="primary" disabled={!task.trim()} onClick={start}>▶ Run</button></div>
    </Modal>
  )
}

function EvalModal({ graphId, graphName, models, onClose }: { graphId: string; graphName: string; models: ModelCfg[]; onClose: () => void }) {
  const toast = useToast()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [scorers, setScorers] = useState<Record<string, string>>({})
  const [f, setF] = useState<any>({ dataset_id: '', scorer: 'auto', judge_model_id: '', concurrency: 4, repeats: 1, limit: '', name: '' })
  useEffect(() => {
    api.datasets().then((d) => { setDatasets(d); if (d.length) setF((x: any) => ({ ...x, dataset_id: d[0].id })) })
    api.meta().then((m) => setScorers(m.scorers))
  }, [])
  const start = async () => {
    try {
      const r = await api.startExperiment({
        graph_id: graphId, dataset_id: f.dataset_id, name: f.name,
        scorer: { type: f.scorer, judge_model_id: f.judge_model_id || undefined },
        concurrency: +f.concurrency, repeats: +f.repeats, limit: f.limit ? +f.limit : null,
      })
      go(`experiments/${r.id}`)
    } catch (e: any) { toast(e.message, true) }
  }
  return (
    <Modal title={`Evaluate “${graphName}”`} onClose={onClose}>
      {!datasets.length && <div className="err">No datasets — upload one on the Datasets page.</div>}
      <label className="field">Dataset
        <select value={f.dataset_id} onChange={(e) => setF({ ...f, dataset_id: e.target.value })}>
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name} ({d.item_count})</option>)}
        </select>
      </label>
      <label className="field"><span>Scorer<Tip text={HINTS.scorer} /></span>
        <select value={f.scorer} onChange={(e) => setF({ ...f, scorer: e.target.value })}>
          {Object.entries(scorers).map(([k, v]) => <option key={k} value={k}>{k} — {v}</option>)}
        </select>
      </label>
      {f.scorer === 'llm_judge' && (
        <label className="field">Judge model
          <select value={f.judge_model_id} onChange={(e) => setF({ ...f, judge_model_id: e.target.value })}>
            <option value="">— select —</option>{models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
      )}
      <div className="grid2">
        <label className="field"><span>Concurrency<Tip text={HINTS.concurrency} /></span><input type="number" min={1} value={f.concurrency} onChange={(e) => setF({ ...f, concurrency: e.target.value })} /></label>
        <label className="field"><span>Repeats per item<Tip text={HINTS.repeats} /></span><input type="number" min={1} value={f.repeats} onChange={(e) => setF({ ...f, repeats: e.target.value })} /></label>
        <label className="field">Limit items<input placeholder="all" value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} /></label>
        <label className="field">Name<input placeholder="auto" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
      </div>
      <div className="row"><span className="spacer" /><button onClick={onClose}>Cancel</button>
        <button className="primary" disabled={!f.dataset_id || (f.scorer === 'llm_judge' && !f.judge_model_id)} onClick={start}>Start experiment</button></div>
    </Modal>
  )
}

function RunDrawer({ run, onClose }: { run: Run; onClose: () => void }) {
  const live = ['queued', 'running'].includes(run.status)
  return (
    <div className="drawer">
      <div className="row">
        <Pill status={run.status} />
        <span className="mono small">{fmtMs(run.duration_ms ?? (run.started_at ? Date.now() - run.started_at * 1000 : null))}</span>
        <span className="mono small muted">{fmtTok(run.input_tokens)} in · {fmtTok(run.output_tokens)} out · {fmtCost(run.cost)} · {run.llm_calls} llm · {run.tool_calls} tools</span>
        {run.correct != null && <Mark v={run.correct} />}
        <span className="spacer" />
        {live && <button className="sm danger" onClick={() => api.cancelRun(run.id)}>Stop</button>}
        <button className="sm" onClick={() => go(`runs/${run.id}`)}>Open trace →</button>
        <button className="sm ghost" onClick={onClose}>✕</button>
      </div>
      <div className="small muted clip" style={{ maxWidth: '100%' }}>Task: {run.task}</div>
      {run.answer != null && <div className={`answer ${run.correct == null ? '' : run.correct ? 'yes' : 'no'}`}>{run.answer}</div>}
      {run.error && <div className="err">{run.error}</div>}
    </div>
  )
}
