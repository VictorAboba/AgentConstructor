export type EdgeKind = 'flow' | 'conditional' | 'feedback' | 'handoff' | 'delegate' | 'message' | 'subscribe'

export interface ModelCfg {
  id: string; name: string; provider: string; model: string; base_url: string; api_key: string
  price_in: number; price_out: number; extra: Record<string, any>
}
export interface GraphRow { id: string; name: string; data: GraphData; updated_at?: number }
export interface GraphData { nodes: any[]; edges: any[]; settings: Record<string, any> }
export interface Span {
  id: string; run_id: string; parent_id: string | null; kind: string; name: string; node_id: string | null
  started_at: number; ended_at: number | null; duration_ms: number | null; status: string
  input_tokens: number; output_tokens: number; cost: number; data: Record<string, any>
}
export interface Run {
  id: string; experiment_id: string | null; graph_id: string; graph_name: string; idx: number; repeat: number
  task: string; expected: string | null; answer: string | null; status: string; correct: number | null
  started_at: number | null; ended_at: number | null; duration_ms: number | null
  input_tokens: number; output_tokens: number; cached_tokens: number; cost: number
  llm_calls: number; tool_calls: number; activations: number; error: string | null; judge_note?: string | null
  node_stats?: Record<string, NodeStats>; graph_snapshot?: GraphData; spans?: Span[]; created_at: number
}
export interface NodeStats {
  activations: number; llm_calls: number; tool_calls: number; input_tokens: number; output_tokens: number
  cached_tokens: number; cost: number; duration_ms: number; errors: number
}
export interface Summary {
  total: number; finished: number; running: number; queued: number; errors: number; scored: number; correct: number
  accuracy: number | null; duration_mean_ms: number | null; duration_median_ms: number | null; duration_p95_ms: number | null
  input_tokens: number; output_tokens: number; cached_tokens: number; tokens_mean: number | null; cost: number
  cost_mean: number | null; llm_calls_mean: number | null; tool_calls_mean: number | null; activations_mean: number | null
  judge_cost: number; judge_tokens: number; nodes: Record<string, NodeStats>
}
export interface Experiment {
  id: string; name: string; graph_id: string; graph_name: string; dataset_id: string; dataset_name: string
  config: Record<string, any>; status: string; created_at: number; started_at: number | null; ended_at: number | null
  summary: Summary; runs?: Run[]; graph_snapshot?: GraphData
}
export interface Template {
  id: string; name: string; category: string; summary: string; measure: string; summary_ru: string; measure_ru: string; agents: number
  preview: { nodes: { id: string; type: string; x: number; y: number; label: string }[]; edges: { source: string; target: string; kind: string; bidirectional: boolean }[] }
}
export interface Dataset { id: string; name: string; description: string; item_count: number; created_at: number; items?: any[] }
export interface Meta {
  providers: Record<string, { label: string; base_url: string; env: string }>
  tools: { name: string; description: string; category: string }[]
  default_tools: string[]
  edge_kinds: EdgeKind[]
  scorers: Record<string, string>
  docker: boolean
  docker_detail: string
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const r = await fetch('/api' + path, init)
  if (!r.ok) {
    let msg = r.statusText
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    throw new Error(msg)
  }
  return r.json()
}

export const api = {
  meta: () => req<Meta>('GET', '/meta'),
  models: () => req<ModelCfg[]>('GET', '/models'),
  createModel: (m: Partial<ModelCfg>) => req<ModelCfg>('POST', '/models', m),
  updateModel: (id: string, m: Partial<ModelCfg>) => req<ModelCfg>('PUT', `/models/${id}`, m),
  deleteModel: (id: string) => req('DELETE', `/models/${id}`),
  testModel: (id: string) => req<any>('POST', `/models/${id}/test`),
  graphs: () => req<GraphRow[]>('GET', '/graphs'),
  graph: (id: string) => req<GraphRow>('GET', `/graphs/${id}`),
  createGraph: (name: string, data: GraphData) => req<GraphRow>('POST', '/graphs', { name, data }),
  updateGraph: (id: string, name: string, data: GraphData) => req<GraphRow>('PUT', `/graphs/${id}`, { name, data }),
  deleteGraph: (id: string) => req('DELETE', `/graphs/${id}`),
  templates: () => req<Template[]>('GET', '/templates'),
  createFromTemplate: (template_id: string, model_id: string, name = '') => req<GraphRow>('POST', '/graphs/from-template', { template_id, model_id, name }),
  validateGraph: (name: string, data: GraphData) => req<{ ok: boolean; errors: string[]; warnings: string[] }>('POST', '/graphs/validate', { name, data }),
  datasets: () => req<Dataset[]>('GET', '/datasets'),
  dataset: (id: string) => req<Dataset>('GET', `/datasets/${id}`),
  uploadDataset: (f: FormData) => req<Dataset>('POST', '/datasets', f),
  deleteDataset: (id: string) => req('DELETE', `/datasets/${id}`),
  startRun: (b: { graph_id: string; task: string; expected?: string | null; scorer?: any }) => req<{ id: string }>('POST', '/runs', b),
  runs: (q = '') => req<Run[]>('GET', `/runs${q}`),
  run: (id: string) => req<Run>('GET', `/runs/${id}`),
  cancelRun: (id: string) => req('POST', `/runs/${id}/cancel`),
  deleteRun: (id: string) => req('DELETE', `/runs/${id}`),
  runFiles: (id: string) => req<{ path: string; size: number }[]>('GET', `/runs/${id}/files`),
  runFile: (id: string, path: string) => req<{ content: string; size: number }>('GET', `/runs/${id}/file?path=${encodeURIComponent(path)}`),
  startExperiment: (b: any) => req<{ id: string }>('POST', '/experiments', b),
  experiments: () => req<Experiment[]>('GET', '/experiments'),
  experiment: (id: string) => req<Experiment>('GET', `/experiments/${id}`),
  cancelExperiment: (id: string) => req('POST', `/experiments/${id}/cancel`),
  deleteExperiment: (id: string) => req('DELETE', `/experiments/${id}`),
}
