/** Thin typed fetch client. No retries, no caching magic, no hidden state. */

import type {
  ArbitrationItem,
  ArbitrationListResponse,
  ArbitrationQueue,
  ArbitrationRunResult,
  ArbitrationSummary,
  AuditListResponse,
  CashPosition,
  CashResilienceResponse,
  CopilotAnswer,
  EvaluationMetrics,
  ExceptionListResponse,
  Explanation,
  ForecastResponse,
  Health,
  JournalListResponse,
  MetricsResponse,
  RecordDetail,
  RecordListResponse,
  Rule,
  RuleCatalogue,
  RuleDemoResponse,
  RunComparison,
  RunSummary,
  TrialBalance,
} from '@/types'

const BASE = '/api'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type Params = Record<string, string | number | boolean | null | undefined>

function qs(params?: Params): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const out = search.toString()
  return out ? `?${out}` : ''
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail
    } catch {
      /* body was not JSON; the status line is the best we have */
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<Health>('/health'),

  generateData: (body: {
    order_count: number
    seed: number
    mode: 'clean' | 'messy'
    dataset_id?: string
  }) =>
    request<{ dataset_id: string; manifest: Record<string, unknown> }>(
      '/data/generate',
      { method: 'POST', body: JSON.stringify(body) },
    ),

  startRun: (body: { dataset_id?: string; label?: string } = {}) =>
    request<RunSummary>('/reconciliation/run', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  runs: (limit = 50) =>
    request<{ runs: RunSummary[]; total: number }>(
      `/reconciliation/runs${qs({ limit })}`,
    ),

  run: (runId: string) => request<RunSummary>(`/reconciliation/runs/${runId}`),

  compareRuns: (baseline: string, candidate: string) =>
    request<RunComparison>(
      `/reconciliation/runs/compare${qs({ baseline, candidate })}`,
    ),

  records: (params?: Params) =>
    request<RecordListResponse>(`/reconciliation/records${qs(params)}`),

  record: (id: string, runId?: string) =>
    request<RecordDetail>(
      `/reconciliation/records/${id}${qs({ run_id: runId })}`,
    ),

  explain: (id: string, runId?: string) =>
    request<Explanation>(
      `/reconciliation/records/${id}/explain${qs({ run_id: runId })}`,
    ),

  exceptions: (params?: Params) =>
    request<ExceptionListResponse>(`/exceptions${qs(params)}`),

  audit: (params?: Params) => request<AuditListResponse>(`/audit${qs(params)}`),

  metrics: (runId?: string) =>
    request<MetricsResponse>(`/metrics${qs({ run_id: runId })}`),

  rules: () =>
    request<{
      rules: Rule[]
      total: number
      by_status: Record<string, number>
      promotion_enabled: boolean
      note: string
    }>('/rules'),

  cashPosition: (runId?: string) =>
    request<CashPosition>(`/cash-position${qs({ run_id: runId })}`),

  arbitrationQueue: (runId?: string, limit = 50) =>
    request<ArbitrationQueue>(`/arbitration/queue${qs({ run_id: runId, limit })}`),

  /* --- intelligence layer ------------------------------------------- */

  runArbitration: (body: {
    run_id?: string
    arbitrator?: string
    propose_rules?: boolean
  }) =>
    request<ArbitrationRunResult>('/arbitration/run', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  arbitrationResults: (params?: Params) =>
    request<ArbitrationListResponse>(`/arbitration/results${qs(params)}`),

  arbitrationDetail: (residualId: string) =>
    request<ArbitrationItem>(`/arbitration/results/${residualId}`),

  approveArbitration: (residualId: string, actor = 'human@finance') =>
    request<{ status: string; residual_id: string; decision: string }>(
      `/arbitration/${residualId}/approve?actor=${encodeURIComponent(actor)}`,
      { method: 'POST' },
    ),

  rejectArbitration: (residualId: string, actor = 'human@finance') =>
    request<{ status: string; residual_id: string; decision: string }>(
      `/arbitration/${residualId}/reject?actor=${encodeURIComponent(actor)}`,
      { method: 'POST' },
    ),

  unresolveArbitration: (residualId: string, actor = 'human@finance') =>
    request<{ status: string; residual_id: string; decision: string }>(
      `/arbitration/${residualId}/unresolve?actor=${encodeURIComponent(actor)}`,
      { method: 'POST' },
    ),

  evaluateArbitration: (runId: string) =>
    request<EvaluationMetrics>(`/arbitration/evaluate/${runId}`),

  aiMetrics: (runId: string) =>
    request<ArbitrationSummary>(`/arbitration/metrics/${runId}`),

  ruleCatalogue: () => request<RuleCatalogue>('/rules'),

  validateRule: (ruleId: string, datasetId?: string) =>
    request<RuleCatalogue>(`/rules/${ruleId}/validate`, {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId ?? null }),
    }),

  decideRule: (
    ruleId: string,
    decision: 'promote' | 'reject' | 'retire',
    actor: string,
    note = '',
  ) =>
    request<RuleCatalogue>(`/rules/${ruleId}/${decision}`, {
      method: 'POST',
      body: JSON.stringify({ actor, note }),
    }),

  runRuleDemo: () =>
    request<RuleDemoResponse>('/rules/demo-scenario', { method: 'POST' }),

  journal: (params?: Params) =>
    request<JournalListResponse>(`/journal${qs(params)}`),

  decideJournal: (
    journalId: string,
    decision: 'APPROVE' | 'REJECT' | 'POST',
    actor: string,
    note = '',
  ) =>
    request<JournalListResponse>(`/journal/${journalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, actor, note }),
    }),

  trialBalance: (runId?: string) =>
    request<TrialBalance>(`/journal/trial-balance${qs({ run_id: runId })}`),

  forecast: (runId?: string, horizonDays = 30) =>
    request<ForecastResponse>(
      `/cash-position/forecast${qs({ run_id: runId, horizon_days: horizonDays })}`,
    ),

  cashResilience: (runId?: string) =>
    request<CashResilienceResponse>(`/cash-position/resilience${qs({ run_id: runId })}`),

  runFullDemoSequence: () =>
    request<Record<string, unknown>>('/demo/full-sequence', { method: 'POST' }),

  askCopilot: (question: string, runId?: string) =>
    request<CopilotAnswer>('/copilot/ask', {
      method: 'POST',
      body: JSON.stringify({ question, run_id: runId ?? null }),
    }),
}
