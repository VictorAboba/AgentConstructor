import { Edge, Handle, MarkerType, NodeProps, Position } from '@xyflow/react'
import { EdgeKind, ModelCfg, NodeStats } from './api'
import { fmtCost, fmtMs, fmtTok } from './ui'

export const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#000'

export const EDGE_KINDS: { kind: EdgeKind; label: string; hint: string }[] = [
  { kind: 'flow', label: 'Flow', hint: 'Output is passed to the target' },
  { kind: 'conditional', label: 'Conditional', hint: 'Passed only if the condition matches' },
  { kind: 'feedback', label: 'Feedback', hint: 'Back-edge for loops, limited by max iterations' },
  { kind: 'handoff', label: 'Handoff', hint: 'Agent decides to transfer control (tool)' },
  { kind: 'delegate', label: 'Delegate', hint: 'Agent calls target as a sub-agent (tool)' },
  { kind: 'message', label: 'Message', hint: 'Agent can write to the target at any time without ending its turn (tool); can be two-way' },
  { kind: 'subscribe', label: 'Subscribe', hint: 'Agent receives the posts of a board — from everyone or from chosen authors' },
]

function condText(c?: { type?: string; value?: string }) {
  if (!c || !c.type || c.type === 'always' || !c.value) return ''
  const op = { contains: '∋', not_contains: '∌', regex: '~' }[c.type] || c.type
  return `${op} ${c.value.length > 14 ? c.value.slice(0, 14) + '…' : c.value}`
}

export function edgeLook(kind: EdgeKind) {
  const ink = cssVar('--ink'), orange = cssVar('--orange'), muted = cssVar('--muted'), green = cssVar('--green')
  switch (kind) {
    case 'conditional': return { stroke: ink, dash: '6 4', width: 1.5, color: ink }
    case 'feedback': return { stroke: orange, dash: '5 4', width: 1.75, color: orange }
    case 'handoff': return { stroke: ink, dash: undefined, width: 2.5, color: ink }
    case 'delegate': return { stroke: muted, dash: '1.5 4', width: 2, color: muted }
    case 'message': return { stroke: green, dash: undefined, width: 1.75, color: green }
    case 'subscribe': return { stroke: green, dash: '4 3', width: 1.5, color: green }
    default: return { stroke: ink, dash: undefined, width: 1.5, color: ink }
  }
}

/** Applies visual style for an edge from its data.kind. */
export function styleEdge(e: Edge, opts: { selected?: boolean; active?: boolean; dim?: boolean; count?: number; names?: Record<string, string> } = {}): Edge {
  const d: any = e.data || {}
  const kind: EdgeKind = d.kind || 'flow'
  const look = edgeLook(kind)
  let label = ''
  if (kind === 'conditional') label = condText(d.condition) || 'if …'
  if (kind === 'feedback') label = `↺ ≤${d.max_iterations || 3}${condText(d.condition) ? ' · ' + condText(d.condition) : ''}`
  if (kind === 'handoff') label = 'handoff'
  if (kind === 'delegate') label = 'delegate'
  if (kind === 'message') label = d.bidirectional ? '✉ ⇄' : '✉'
  if (kind === 'subscribe') {
    const authors: string[] = d.authors || []
    const who = authors.map((a) => opts.names?.[a] || a).join(', ')
    label = authors.length ? `subscribe · ${who.length > 24 ? `${authors.length} authors` : who}` : 'subscribe'
  }
  if (opts.count) label = `${label ? label + ' · ' : ''}×${opts.count}`
  const width = (e.selected ? 1 : 0) + look.width + (opts.active ? 1.5 : 0)
  return {
    ...e,
    type: kind === 'feedback' ? 'default' : 'smoothstep',
    animated: !!opts.active,
    label: label || undefined,
    labelBgPadding: [4, 2],
    labelBgBorderRadius: 3,
    style: { stroke: opts.active ? cssVar('--orange') : look.stroke, strokeWidth: width, strokeDasharray: look.dash, opacity: opts.dim ? 0.3 : 1 },
    markerEnd: kind === 'delegate'
      ? { type: MarkerType.Arrow, color: look.color, width: 16, height: 16 }
      : { type: MarkerType.ArrowClosed, color: look.color, width: 16, height: 16 },
    markerStart: kind === 'message' && d.bidirectional ? { type: MarkerType.ArrowClosed, color: look.color, width: 16, height: 16 } : undefined,
  }
}

export interface NodeView {
  label?: string
  _status?: 'running' | 'ok' | 'error' | 'waiting'
  _focus?: boolean
  _dim?: boolean
  _inbox?: number
  _stats?: NodeStats
  _models?: Record<string, ModelCfg>
  [k: string]: any
}

function Stats({ s }: { s?: NodeStats }) {
  if (!s || !s.activations) return null
  return (
    <div className="stats">
      <span>×{s.activations}</span>
      <span>{fmtTok(s.input_tokens + s.output_tokens)} tok</span>
      <span>{fmtMs(s.duration_ms)}</span>
      {s.cost > 0 && <span>{fmtCost(s.cost)}</span>}
    </div>
  )
}

const statusCls = (d: NodeView) => (d._status ? ` st-${d._status}` : '') + (d._focus ? ' focus' : '') + (d._dim ? ' dim' : '')

const Inbox = ({ d }: { d: NodeView }) => (d._inbox ? <span className="inbox" title="Delivered messages not yet processed">✉ {d._inbox}</span> : null)

function AgentNode({ data, selected }: NodeProps) {
  const d = data as NodeView
  const model = d._models?.[d.model_id]
  const tools: string[] = d.tools || []
  return (
    <div className={`gnode${selected ? ' selected' : ''}${statusCls(d)}`}>
      <Handle type="target" position={Position.Left} />
      <div className="hd">
        {d._status && <span className={`dot ${d._status}`} />}
        <span>{d.label || 'Agent'}</span><Inbox d={d} /><span className="type">agent</span>
      </div>
      <div className="bd">
        <span className={model ? '' : 'c-red'}>{model ? model.name : 'no model'}</span>
        <span className="small faint">{tools.length ? tools.join(' · ') : 'no tools'}</span>
        <Stats s={d._stats} />
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function IONode({ data, selected, type }: NodeProps) {
  const d = data as NodeView
  return (
    <div className={`gnode io${selected ? ' selected' : ''}${statusCls(d)}`}>
      {type !== 'input' && <Handle type="target" position={Position.Left} />}
      <div className="hd"><span>{d.label || type}</span><Inbox d={d} /><span className="type">{type}</span></div>
      {type !== 'output' && <Handle type="source" position={Position.Right} />}
    </div>
  )
}

function VoteNode({ data, selected }: NodeProps) {
  const d = data as NodeView
  return (
    <div className={`gnode vote${selected ? ' selected' : ''}${statusCls(d)}`}>
      <Handle type="target" position={Position.Left} />
      <div className="hd"><span>{d.label || 'Vote'}</span><Inbox d={d} /><span className="type">vote</span></div>
      <div className="bd"><span className="small">majority over inputs</span></div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function BoardNode({ data, selected }: NodeProps) {
  const d = data as NodeView
  return (
    <div className={`gnode board${selected ? ' selected' : ''}${statusCls(d)}`}>
      <Handle type="target" position={Position.Left} />
      <div className="hd"><span>▤ {d.label || 'Board'}</span><span className="type">board</span></div>
      <div className="bd">
        <span className="small">{d._posts ? `${d._posts} post${d._posts > 1 ? 's' : ''}` : 'message board'}</span>
        {d._lastPost && <span className="small faint clip" style={{ maxWidth: 190 }}>{d._lastPost}</span>}
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export const nodeTypes = { agent: AgentNode, input: IONode, output: IONode, vote: VoteNode, board: BoardNode }

export function EdgeLegend() {
  return (
    <div className="legend">
      {EDGE_KINDS.map(({ kind, label }) => {
        const l = edgeLook(kind)
        return (
          <div key={kind}>
            <svg width="30" height="8"><line x1="0" y1="4" x2="30" y2="4" stroke={l.stroke} strokeWidth={l.width} strokeDasharray={l.dash} /></svg>
            {label}
          </div>
        )
      })}
    </div>
  )
}
