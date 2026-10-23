import { useEffect, useState } from 'react'
import { Meta, ModelCfg, api } from '../api'
import { HINTS } from '../hints'
import { Modal, Tip, fmtMs, usePoll, useToast } from '../ui'

const PRESETS: Record<string, { model: string; price_in: number; price_out: number }[]> = {
  anthropic: [
    { model: 'claude-opus-5-5', price_in: 4, price_out: 20 },
    { model: 'claude-sonnet-5-5', price_in: 2, price_out: 10 },
    { model: 'claude-haiku-5-5', price_in: 0.1, price_out: 0.5 },
    { model: 'claude-fable-5-1', price_in: 10, price_out: 50 },
  ],
  openai: [{ model: 'gpt-5', price_in: 0, price_out: 0 }],
  openrouter: [{ model: 'anthropic/claude-sonnet-5-5', price_in: 2, price_out: 10 }],
  vllm: [{ model: 'Qwen/Qwen3-8B', price_in: 0, price_out: 0 }],
  ollama: [{ model: 'qwen3:8b', price_in: 0, price_out: 0 }],
  mock: [{ model: 'mock-1', price_in: 1, price_out: 5 }],
}

const EMPTY: Partial<ModelCfg> = { name: '', provider: 'anthropic', model: 'claude-opus-5-5', base_url: '', api_key: '', price_in: 4, price_out: 20, extra: {} }

export default function Models() {
  const toast = useToast()
  const { data, reload } = usePoll(() => api.models(), [])
  const [meta, setMeta] = useState<Meta | null>(null)
  const [edit, setEdit] = useState<Partial<ModelCfg> | null>(null)
  const [tests, setTests] = useState<Record<string, any>>({})
  useEffect(() => { api.meta().then(setMeta) }, [])

  const test = async (m: ModelCfg) => {
    setTests((t) => ({ ...t, [m.id]: { pending: true } }))
    const r = await api.testModel(m.id).catch((e) => ({ ok: false, error: e.message }))
    setTests((t) => ({ ...t, [m.id]: r }))
  }

  return (
    <div className="page">
      <div className="page-head"><h1>Models</h1><span className="muted">provider connections used by agents</span><span className="spacer" />
        <button className="primary" onClick={() => setEdit({ ...EMPTY })}>＋ Add model</button></div>
      <table className="t">
        <thead><tr><th>Name</th><th>Provider</th><th>Model</th><th>Endpoint</th><th>Key</th><th className="num">$ / 1M in · out</th><th>Check</th><th></th></tr></thead>
        <tbody>
          {data?.map((m) => {
            const t = tests[m.id]
            return (
              <tr key={m.id}>
                <td><b>{m.name}</b></td><td>{meta?.providers[m.provider]?.label || m.provider}</td><td className="mono small">{m.model}</td>
                <td className="mono small muted">{m.base_url || meta?.providers[m.provider]?.base_url || 'default'}</td>
                <td className="mono small muted">{m.api_key || (meta?.providers[m.provider]?.env ? `$${meta.providers[m.provider].env}` : '—')}</td>
                <td className="num">{m.price_in} · {m.price_out}</td>
                <td className="small">
                  <button className="sm" onClick={() => test(m)}>Test</button>{' '}
                  {t?.pending && <span className="c-orange">…</span>}
                  {t && !t.pending && (t.ok ? <span className="c-green">OK · {fmtMs(t.latency_ms)}</span> : <span className="c-red" title={t.error}>failed</span>)}
                  {t && !t.pending && !t.ok && <div className="small c-red clip" style={{ maxWidth: 260 }} title={t.error}>{t.error}</div>}
                </td>
                <td><button className="sm ghost" onClick={() => setEdit(m)}>Edit</button>
                  <button className="sm ghost danger" onClick={async () => { if (confirm(`Delete ${m.name}?`)) { await api.deleteModel(m.id); reload() } }}>✕</button></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="small muted">Keys left empty are read from environment variables (<code>OPENAI_API_KEY</code>, <code>ANTHROPIC_API_KEY</code>, <code>OPENROUTER_API_KEY</code>). Stored keys live in the local SQLite file under <code>data/</code>.</p>
      {edit && meta && <ModelForm init={edit} meta={meta} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); toast('Saved') }} />}
    </div>
  )
}

function ModelForm({ init, meta, onClose, onSaved }: { init: Partial<ModelCfg>; meta: Meta; onClose: () => void; onSaved: () => void }) {
  const toast = useToast()
  const [m, setM] = useState<any>({ ...init, extra: { ...(init.extra || {}) } })
  const [body, setBody] = useState(JSON.stringify(m.extra.body || {}, null, 2))
  const set = (p: any) => setM({ ...m, ...p })
  const setExtra = (p: any) => setM({ ...m, extra: { ...m.extra, ...p } })
  const isAnthropic = m.provider === 'anthropic'

  const save = async () => {
    let parsed = {}
    try { parsed = body.trim() ? JSON.parse(body) : {} } catch { return toast('Extra body is not valid JSON', true) }
    const payload = { ...m, name: m.name || m.model, extra: { ...m.extra, body: parsed } }
    try {
      if (m.id) await api.updateModel(m.id, payload)
      else await api.createModel(payload)
      onSaved()
    } catch (e: any) { toast(e.message, true) }
  }

  return (
    <Modal title={m.id ? 'Edit model' : 'Add model'} onClose={onClose}>
      <div className="grid2">
        <label className="field">Provider
          <select value={m.provider} onChange={(e) => {
            const p = e.target.value; const pre = PRESETS[p]?.[0]
            set({ provider: p, base_url: '', ...(pre && !m.id ? pre : {}) })
          }}>
            {Object.entries(meta.providers).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
        <label className="field">Display name<input value={m.name} placeholder={m.model} onChange={(e) => set({ name: e.target.value })} /></label>
      </div>
      <label className="field">Model
        <input value={m.model} list="model-presets" onChange={(e) => {
          const pre = PRESETS[m.provider]?.find((x) => x.model === e.target.value)
          set({ model: e.target.value, ...(pre ? { price_in: pre.price_in, price_out: pre.price_out } : {}) })
        }} />
        <datalist id="model-presets">{PRESETS[m.provider]?.map((p) => <option key={p.model} value={p.model} />)}</datalist>
      </label>
      {m.provider !== 'mock' && (
        <>
          <label className="field">Base URL<input value={m.base_url} placeholder={meta.providers[m.provider]?.base_url || 'provider default'} onChange={(e) => set({ base_url: e.target.value })} /></label>
          <label className="field">API key<input type="password" value={m.api_key} placeholder={meta.providers[m.provider]?.env ? `empty → $${meta.providers[m.provider].env}` : 'not required'} onChange={(e) => set({ api_key: e.target.value })} /></label>
        </>
      )}
      <div className="grid2">
        <label className="field"><span>Price in, $ / 1M tok<Tip text={HINTS.price} /></span><input type="number" step="0.01" value={m.price_in} onChange={(e) => set({ price_in: +e.target.value })} /></label>
        <label className="field">Price out, $ / 1M tok<input type="number" step="0.01" value={m.price_out} onChange={(e) => set({ price_out: +e.target.value })} /></label>
      </div>
      {isAnthropic && (
        <div className="col">
          <label className="check"><input type="checkbox" checked={m.extra.prompt_cache !== false} onChange={(e) => setExtra({ prompt_cache: e.target.checked })} />Prompt caching (cheaper multi-step agent loops)<Tip text={HINTS.promptCache} /></label>
          <label className="check"><input type="checkbox" checked={m.extra.reasoning_summary !== false} onChange={(e) => setExtra({ reasoning_summary: e.target.checked })} />Record reasoning summaries in traces<Tip text={HINTS.reasoningSummary} /></label>
          <label className="check"><input type="checkbox" checked={m.extra.fallbacks !== false} onChange={(e) => setExtra({ fallbacks: e.target.checked })} />Server-side refusal fallback (<code>fallbacks: "default"</code>)<Tip text={HINTS.fallback} /></label>
          <span className="hint">With fallback on, a declined request may be answered by another model; the trace marks this as “served by”. Turn off for strict single-model comparisons.</span>
        </div>
      )}
      <label className="field">Extra request body (JSON)<textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
        <span className="hint">Merged into every request, e.g. <code>{'{"top_p": 0.9}'}</code> for vLLM.</span></label>
      <div className="row"><span className="spacer" /><button onClick={onClose}>Cancel</button><button className="primary" onClick={save}>Save</button></div>
    </Modal>
  )
}
