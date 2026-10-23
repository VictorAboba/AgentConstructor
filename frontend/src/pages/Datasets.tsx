import { useRef, useState } from 'react'
import { api } from '../api'
import { HINTS } from '../hints'
import { Tip, ago, usePoll, useToast } from '../ui'

const EXAMPLE = `{"task": "What is 17 + 25?", "answer": "42"}
{"question": "Fix the bug in calc.py so tests pass. Reply DONE.", "answer": "DONE",
 "files": {"calc.py": "def add(a, b):\\n    return a - b\\n"}, "setup": "pip install -q pytest"}
{"task": "Make the tests in this repo pass. Reply DONE.", "answer": "DONE",
 "files": "C:/bench/repo1", "files_glob": "**/*.py; !**/__pycache__/**"}`

/** Short description of what an item seeds into the sandbox. */
function filesNote(meta: any): string | null {
  const ff = meta?.files_from
  if (ff) return `📁 ${ff.dir}${ff.glob?.length ? ' · ' + ff.glob.join('; ') : ''}`
  const inline = meta?.files && Object.keys(meta.files)
  return inline?.length ? `files: ${inline.join(', ')}` : null
}

export default function Datasets({ id }: { id?: string }) {
  const toast = useToast()
  const list = usePoll(() => api.datasets(), [])
  const ds = usePoll(() => (id ? api.dataset(id) : Promise.resolve(null)), [id])
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [filesDir, setFilesDir] = useState('')
  const [filesGlob, setFilesGlob] = useState('')
  const [busy, setBusy] = useState(false)

  const upload = async () => {
    const f = fileRef.current?.files?.[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    fd.append('name', name)
    fd.append('files_dir', filesDir)
    fd.append('files_glob', filesGlob)
    setBusy(true)
    try {
      const d = await api.uploadDataset(fd)
      toast(`Loaded ${d.item_count} items`)
      setName('')
      setFilesDir('')
      setFilesGlob('')
      if (fileRef.current) fileRef.current.value = ''
      list.reload()
      window.location.hash = `#/datasets/${d.id}`
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }

  return (
    <div className="page">
      <div className="page-head"><h1>Datasets</h1><span className="muted">task + reference answer sets</span></div>
      <div className="grid2" style={{ alignItems: 'start' }}>
        <div className="card col">
          <h3>Upload</h3>
          <div className="row">
            <input ref={fileRef} type="file" accept=".jsonl,.json,.csv,.tsv" style={{ flex: 1 }} />
            <input placeholder="name (optional)" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 180 }} />
            <button className="primary" onClick={upload} disabled={busy}>Upload</button>
          </div>
          <div className="row">
            <label className="field" style={{ flex: 2 }}><span>Files folder (optional)<Tip text={HINTS.filesDir} /></span>
              <input className="mono" placeholder="C:/bench/repo  or  tasks/{id}" value={filesDir} onChange={(e) => setFilesDir(e.target.value)} /></label>
            <label className="field" style={{ flex: 1 }}><span>Glob (optional)<Tip text={HINTS.filesGlob} /></span>
              <input className="mono" placeholder="**/*.py; !tests/**" value={filesGlob} onChange={(e) => setFilesGlob(e.target.value)} disabled={!filesDir.trim()} /></label>
          </div>
          <span className="small muted">JSONL, JSON array or CSV. Task field: <code>task|question|input|prompt|problem</code>; answer: <code>answer|expected|output|target|solution</code>.
            Optional <code>files</code> — inline <code>{'{path: content}'}</code>, a folder path, or <code>{'{"dir": …, "glob": …}'}</code> (plus <code>files_glob</code> as a separate column);
            folders are copied into the sandbox when each run starts. Optional <code>setup</code> — shell command.</span>
          <pre className="answer small">{EXAMPLE}</pre>
        </div>
        <div>
          {!list.data?.length ? <div className="empty">No datasets.</div> : (
            <table className="t">
              <thead><tr><th>Name</th><th className="num">Items</th><th>Created</th><th></th></tr></thead>
              <tbody>
                {list.data.map((d) => (
                  <tr key={d.id} className="click" onClick={() => { window.location.hash = `#/datasets/${d.id}` }} style={id === d.id ? { outline: '1.5px solid var(--ink)' } : {}}>
                    <td>{d.name}<div className="small muted">{d.description}</div></td><td className="num">{d.item_count}</td>
                    <td className="small muted">{ago(d.created_at)}</td>
                    <td onClick={(e) => e.stopPropagation()}><button className="sm ghost danger" onClick={async () => {
                      if (confirm(`Delete dataset ${d.name}?`)) { await api.deleteDataset(d.id); list.reload(); if (id === d.id) window.location.hash = '#/datasets' }
                    }}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      {ds.data && (
        <>
          <h2>{ds.data.name} · {ds.data.item_count} items</h2>
          <table className="t">
            <thead><tr><th>#</th><th>Task</th><th>Answer</th><th>Extras</th></tr></thead>
            <tbody>
              {ds.data.items?.slice(0, 500).map((it: any) => (
                <tr key={it.id}><td className="mono small">{it.idx}</td>
                  <td style={{ maxWidth: 560 }}><pre className="small" style={{ maxHeight: 90, overflow: 'hidden' }}>{it.task}</pre></td>
                  <td className="mono small" style={{ maxWidth: 220 }}>{it.answer}</td>
                  <td className="small muted" style={{ maxWidth: 320 }}>
                    {filesNote(it.meta) && <div className="mono" style={{ wordBreak: 'break-all' }}>{filesNote(it.meta)}</div>}
                    {Object.keys(it.meta || {}).filter((k) => k !== 'files' && k !== 'files_from').join(', ')}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
