import { ReactNode, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

// ---- formatting ---------------------------------------------------------------------------
export const fmtMs = (ms?: number | null) => {
  if (ms == null) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`
}
export const fmtNum = (n?: number | null, digits = 0) =>
  n == null ? '—' : n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
export const fmtTok = (n?: number | null) => {
  if (n == null) return '—'
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (n >= 1e4) return `${(n / 1e3).toFixed(1)}k`
  return fmtNum(n)
}
export const fmtCost = (c?: number | null) => (c == null ? '—' : c === 0 ? '$0' : c < 0.01 ? `$${c.toFixed(4)}` : `$${c.toFixed(3)}`)
export const fmtPct = (p?: number | null) => (p == null ? '—' : `${(p * 100).toFixed(1)}%`)
export const fmtTime = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString() : '—')
export const ago = (t?: number | null) => {
  if (!t) return '—'
  const s = Date.now() / 1000 - t
  if (s < 60) return `${Math.round(s)}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return new Date(t * 1000).toLocaleDateString()
}

export const Pill = ({ status }: { status: string }) => <span className={`pill ${status}`}>{status}</span>
export const Mark = ({ v }: { v: number | null | undefined }) =>
  v == null ? <span className="faint">·</span> : v ? <span className="mark yes">✓</span> : <span className="mark no">✗</span>

export const Stat = ({ k, v, s }: { k: string; v: ReactNode; s?: ReactNode }) => (
  <div className="stat"><div className="k">{k}</div><div className="v">{v}</div>{s != null && <div className="s">{s}</div>}</div>
)

/** "?" badge with an explanation popover on hover. Rendered fixed so it is never clipped by panels. */
export function Tip({ text }: { text: ReactNode }) {
  const [pos, setPos] = useState<{ left: number; top?: number; bottom?: number } | null>(null)
  const show = (el: HTMLElement) => {
    const r = el.getBoundingClientRect()
    const left = Math.max(8, Math.min(r.left - 8, window.innerWidth - 316))
    setPos(r.bottom > window.innerHeight - 160 ? { left, bottom: window.innerHeight - r.top + 6 } : { left, top: r.bottom + 6 })
  }
  return (
    <span className="tip" tabIndex={0} onMouseEnter={(e) => show(e.currentTarget)} onMouseLeave={() => setPos(null)}
      onFocus={(e) => show(e.currentTarget)} onBlur={() => setPos(null)} onClick={(e) => e.preventDefault()}>
      ?{pos && <span className="tip-pop" style={pos}>{text}</span>}
    </span>
  )
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? ' wide' : ''}`}>
        <div className="row"><h3 style={{ margin: 0 }}>{title}</h3><span className="spacer" /><button className="ghost sm" onClick={onClose}>✕</button></div>
        {children}
      </div>
    </div>
  )
}

// ---- toasts -------------------------------------------------------------------------------
const ToastCtx = createContext<(msg: string, error?: boolean) => void>(() => {})
export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<{ msg: string; error: boolean } | null>(null)
  const timer = useRef<number>()
  const show = useCallback((msg: string, error = false) => {
    setT({ msg, error })
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setT(null), error ? 6000 : 2500)
  }, [])
  return <ToastCtx.Provider value={show}>{children}{t && <div className={`toast ${t.error ? 'error' : ''}`}>{t.msg}</div>}</ToastCtx.Provider>
}
export const useToast = () => useContext(ToastCtx)

// ---- data hooks ---------------------------------------------------------------------------
/** Fetches on mount / deps change and re-fetches every `interval` ms while `live(data)` is true. */
export function usePoll<T>(fn: () => Promise<T>, deps: unknown[], interval = 1000, live?: (d: T) => boolean) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    let timer: number | undefined
    const load = async () => {
      try {
        const d = await fn()
        if (!alive) return
        setData(d)
        setError(null)
        if (live && live(d)) timer = window.setTimeout(load, interval)
      } catch (e: any) {
        if (alive) setError(e.message)
      }
    }
    load()
    return () => { alive = false; window.clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, reload: () => setTick((x) => x + 1), setData }
}

// ---- routing ------------------------------------------------------------------------------
export function useHashRoute(): string[] {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const h = () => setHash(window.location.hash)
    window.addEventListener('hashchange', h)
    return () => window.removeEventListener('hashchange', h)
  }, [])
  return hash.replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean)
}
export const go = (path: string) => { window.location.hash = '#/' + path.replace(/^\//, '') }
export const hashQuery = () => new URLSearchParams(window.location.hash.split('?')[1] || '')
