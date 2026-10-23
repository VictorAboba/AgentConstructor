import { useEffect, useState } from 'react'
import { EdgeKind, ModelCfg, Template, api } from './api'
import { cssVar, edgeLook } from './flow'
import { Modal, go, useToast } from './ui'

const NODE_W = 200
const NODE_H = 80

/** Schematic of a template: node boxes and coloured links, scaled to fit the card. */
function Preview({ t }: { t: Template }) {
  const { nodes, edges } = t.preview
  const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y)
  const minX = Math.min(...xs) - 20, minY = Math.min(...ys) - 20
  const w = Math.max(...xs) + NODE_W + 20 - minX, h = Math.max(...ys) + NODE_H + 20 - minY
  const pos = Object.fromEntries(nodes.map((n) => [n.id, n]))
  const ink = cssVar('--ink'), panel = cssVar('--panel'), green = cssVar('--green')
  return (
    <svg viewBox={`${minX} ${minY} ${w} ${h}`} className="tpl-preview" preserveAspectRatio="xMidYMid meet">
      {edges.map((e, i) => {
        const a = pos[e.source], b = pos[e.target]
        if (!a || !b) return null
        const look = edgeLook(e.kind as EdgeKind)
        const back = b.x < a.x
        const x1 = back ? a.x : a.x + NODE_W, x2 = back ? b.x + NODE_W : b.x
        return <line key={i} x1={x1} y1={a.y + NODE_H / 2} x2={x2} y2={b.y + NODE_H / 2} stroke={look.stroke}
          strokeWidth={look.width * 4} strokeDasharray={look.dash?.split(' ').map((v) => +v * 4).join(' ')} opacity={0.9} />
      })}
      {nodes.map((n) => {
        const io = n.type === 'input' || n.type === 'output'
        return (
          <g key={n.id}>
            <title>{n.label} ({n.type})</title>
            <rect x={n.x} y={n.y} width={io ? NODE_W * 0.6 : NODE_W} height={io ? NODE_H * 0.6 : NODE_H} rx={14}
              fill={io ? ink : panel} stroke={n.type === 'board' ? green : ink} strokeWidth={n.type === 'board' ? 14 : 6}
              strokeDasharray={n.type === 'vote' ? '18 10' : undefined} />
          </g>
        )
      })}
    </svg>
  )
}

export default function TemplateGallery({ models, onClose, onBlank }: { models: ModelCfg[]; onClose: () => void; onBlank: () => void }) {
  const toast = useToast()
  const [templates, setTemplates] = useState<Template[]>([])
  const realModels = models.filter((m) => m.provider !== 'mock')
  const [modelId, setModelId] = useState((realModels[0] || models[0])?.id || '')
  useEffect(() => { api.templates().then(setTemplates).catch((e) => toast(e.message, true)) }, [toast])

  const create = async (t: Template) => {
    try {
      const g = await api.createFromTemplate(t.id, modelId)
      onClose()
      go(`graphs/${g.id}`)
    } catch (e: any) { toast(e.message, true) }
  }

  return (
    <Modal title="New graph" onClose={onClose} wide>
      <div className="row">
        <span className="small muted">Start from a typical architecture; every agent gets the model below (change per agent later).</span>
        <span className="spacer" />
        <select value={modelId} onChange={(e) => setModelId(e.target.value)} style={{ width: 260 }}>
          {models.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.provider}/{m.model}</option>)}
        </select>
      </div>
      <div className="tpl-grid">
        <button className="tpl-card tpl-blank" onClick={() => { onClose(); onBlank() }}>
          <div className="tpl-preview tpl-blank-icon">＋</div>
          <b>Blank graph</b><span className="small muted">Input → one agent → Output, build the rest yourself.</span>
        </button>
        {templates.map((t) => (
          <button key={t.id} className="tpl-card" onClick={() => create(t)} disabled={!modelId}>
            <Preview t={t} />
            <span className="tpl-cat">{t.category}</span>
            <div className="row" style={{ gap: 6 }}><b>{t.name}</b><span className="spacer" /><span className="small faint mono">{t.agents} agent{t.agents > 1 ? 's' : ''}</span></div>
            <span className="small">{t.summary}</span>
            <span className="small muted"><b>Что измерять:</b> {t.measure}</span>
          </button>
        ))}
      </div>
    </Modal>
  )
}
