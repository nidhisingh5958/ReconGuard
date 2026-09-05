/**
 * Reconciliation: the dense working table plus run comparison.
 *
 * Every row is one reconciliation decision. Clicking a row opens the drawer
 * that proves it. The Evidence column shows a count rather than a preview,
 * because a truncated fact is worse than a number that tells you how much
 * there is to read.
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { RecordDrawer } from '@/components/RecordDrawer'
import {
  ConfidenceBar,
  EmptyState,
  ErrorState,
  Loading,
  Money,
  Panel,
  PercentDelta,
  StatusBadge,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import {
  formatINR,
  formatMs,
  formatNumber,
  formatPercent,
  formatThroughput,
} from '@/lib/format'
import { MATCH_TYPE_LABELS, STATUS_ORDER, statusStyle } from '@/lib/status'

const PAGE_SIZE = 100

export function Reconciliation() {
  const { activeRunId } = useRunContext()
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [search, setSearch] = useState('')

  const tab = params.get('tab') ?? 'records'
  const status = params.get('status') ?? ''

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next)
    setOffset(0)
  }

  const { data, error, loading } = useApi(
    () =>
      api.records({
        run_id: activeRunId ?? undefined,
        status: status || undefined,
        search: search || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [activeRunId, status, search, offset],
    { enabled: Boolean(activeRunId) },
  )

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <div className="flex items-center gap-2">
        <TabButton active={tab === 'records'} onClick={() => setParam('tab', '')}>
          Records
        </TabButton>
        <TabButton active={tab === 'runs'} onClick={() => setParam('tab', 'runs')}>
          Run comparison
        </TabButton>
      </div>

      {tab === 'runs' ? (
        <RunComparison />
      ) : (
        <Panel
          className="min-h-0 flex-1"
          bodyClassName="flex flex-col min-h-0"
          title={`Reconciliation records${data ? ` · ${formatNumber(data.total)}` : ''}`}
          actions={
            <div className="flex items-center gap-2">
              <input
                className="input w-52"
                placeholder="Search order, payment, invoice…"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  setOffset(0)
                }}
              />
              <select
                className="input"
                value={status}
                onChange={(event) => setParam('status', event.target.value)}
              >
                <option value="">All statuses</option>
                {STATUS_ORDER.map((s) => (
                  <option key={s} value={s}>
                    {statusStyle(s).label}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          {loading ? <Loading label="Loading records" /> : null}
          {error ? <ErrorState message={error} /> : null}
          {data && !loading ? (
            <>
              <div className="min-h-0 flex-1 overflow-auto">
                <table className="w-full border-collapse">
                  <thead>
                    <tr>
                      <th className="th">Status</th>
                      <th className="th">Order</th>
                      <th className="th">Payment</th>
                      <th className="th">Settlement</th>
                      <th className="th text-right">Gross</th>
                      <th className="th text-right">Expected net</th>
                      <th className="th text-right">Actual net</th>
                      <th className="th text-right">Variance</th>
                      <th className="th">Match method</th>
                      <th className="th">Confidence</th>
                      <th className="th text-right">Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.records.map((record) => (
                      <tr
                        key={record.reconciliation_id}
                        className="row"
                        onClick={() => setSelected(record.reconciliation_id)}
                      >
                        <td className="td">
                          <StatusBadge status={record.status} />
                        </td>
                        <td className="td num text-accent">{record.order_id ?? '—'}</td>
                        <td className="td num text-ink-2">{record.payment_id ?? '—'}</td>
                        <td className="td num text-ink-2">
                          {record.settlement_ids[0] ?? '—'}
                          {record.settlement_ids.length > 1 ? (
                            <span className="ml-1 text-ink-3">
                              +{record.settlement_ids.length - 1}
                            </span>
                          ) : null}
                        </td>
                        <td className="td text-right">
                          <Money paisa={record.gross_amount_paisa} muted />
                        </td>
                        <td className="td text-right">
                          <Money paisa={record.expected_amount_paisa} />
                        </td>
                        <td className="td text-right">
                          <Money paisa={record.actual_amount_paisa} />
                        </td>
                        <td className="td text-right">
                          <Money paisa={record.variance_paisa} variance />
                        </td>
                        <td className="td text-xs text-ink-2">
                          {MATCH_TYPE_LABELS[record.match_type] ?? record.match_type}
                        </td>
                        <td className="td">
                          <ConfidenceBar value={record.confidence} />
                        </td>
                        <td className="td num text-right text-ink-3">
                          {record.evidence_count}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex shrink-0 items-center justify-between border-t border-line px-3 py-2 text-xs text-ink-3">
                <span className="num">
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of{' '}
                  {formatNumber(data.total)}
                </span>
                <div className="flex gap-1.5">
                  <button
                    className="btn h-6"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  >
                    Previous
                  </button>
                  <button
                    className="btn h-6"
                    disabled={offset + PAGE_SIZE >= data.total}
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                  >
                    Next
                  </button>
                </div>
              </div>
            </>
          ) : null}
        </Panel>
      )}

      <RecordDrawer
        reconciliationId={selected}
        runId={activeRunId}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'h-7 rounded border px-3 text-sm transition-colors',
        active
          ? 'border-accent/40 bg-accent/10 text-accent'
          : 'border-line-strong bg-raised text-ink-2 hover:text-ink',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

/**
 * Run comparison. This is the surface that will later demonstrate self-healing
 * rules: run the same dataset before and after a rule is promoted and read the
 * deterministic-match improvement and residual reduction directly.
 */
function RunComparison() {
  const { runs } = useRunContext()
  const [baseline, setBaseline] = useState(runs[1]?.run_id ?? runs[0]?.run_id ?? '')
  const [candidate, setCandidate] = useState(runs[0]?.run_id ?? '')

  const { data, error, loading } = useApi(
    () => api.compareRuns(baseline, candidate),
    [baseline, candidate],
    { enabled: Boolean(baseline && candidate) },
  )

  if (runs.length < 2) {
    return (
      <EmptyState
        title="Two runs are needed to compare"
        detail="Run the engine again, optionally after changing a rule or the dataset, then return here."
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <Panel
        title="Run comparison"
        actions={
          <div className="flex items-center gap-2 text-xs">
            <select
              className="input num"
              value={baseline}
              onChange={(e) => setBaseline(e.target.value)}
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id}
                  {r.label ? ` · ${r.label}` : ''}
                </option>
              ))}
            </select>
            <span className="text-ink-3">vs</span>
            <select
              className="input num"
              value={candidate}
              onChange={(e) => setCandidate(e.target.value)}
            >
              {runs.map((r) => (
                <option key={r.run_id} value={r.run_id}>
                  {r.run_id}
                  {r.label ? ` · ${r.label}` : ''}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {loading ? <Loading /> : null}
        {error ? <ErrorState message={error} /> : null}
        {data ? (
          <div className="grid grid-cols-1 divide-y divide-line lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            <RunColumn run={data.baseline} caption="Baseline" />
            <RunColumn run={data.candidate} caption="Candidate" />
            <div className="px-4 py-3">
              <div className="label mb-3">Delta</div>
              <dl className="space-y-2.5">
                <DeltaRow
                  label="Deterministic match improvement"
                  value={
                    <PercentDelta value={data.deterministic_match_improvement_pct} />
                  }
                  sub={`${data.deterministic_match_delta >= 0 ? '+' : ''}${data.deterministic_match_delta} records`}
                />
                <DeltaRow
                  label="Residual reduction"
                  value={<PercentDelta value={data.residual_reduction_pct} />}
                  sub={`${data.residual_delta >= 0 ? '+' : ''}${data.residual_delta} residuals`}
                />
                <DeltaRow
                  label="Match rate change"
                  value={<PercentDelta value={data.match_rate_delta_pct} />}
                />
                <DeltaRow
                  label="Throughput change"
                  value={
                    <span className="num">
                      {data.throughput_delta_rps >= 0 ? '+' : ''}
                      {formatNumber(Math.round(data.throughput_delta_rps))}/s
                    </span>
                  }
                />
                <DeltaRow
                  label="Unexplained value change"
                  value={
                    <Money
                      paisa={data.unexplained_value_delta_paisa}
                      variance
                    />
                  }
                />
              </dl>
            </div>
          </div>
        ) : null}
      </Panel>

      {data && Object.keys(data.reason_code_deltas).length > 0 ? (
        <Panel title="Reason code movement">
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 px-4 py-3 md:grid-cols-3">
            {Object.entries(data.reason_code_deltas).map(([code, delta]) => (
              <div key={code} className="flex items-baseline justify-between text-sm">
                <span className="text-ink-2">
                  {code.replace(/_/g, ' ').toLowerCase()}
                </span>
                <span
                  className={`num ${delta < 0 ? 'text-matched' : 'text-exception'}`}
                >
                  {delta > 0 ? '+' : ''}
                  {delta}
                </span>
              </div>
            ))}
          </div>
        </Panel>
      ) : data ? (
        <Panel>
          <div className="px-4 py-3 text-sm text-ink-2">
            No reason codes moved between these runs. Identical input through a
            deterministic engine produces identical output, which is the point.
          </div>
        </Panel>
      ) : null}
    </div>
  )
}

function RunColumn({
  run,
  caption,
}: {
  run: import('@/types').RunSummary
  caption: string
}) {
  return (
    <div className="px-4 py-3">
      <div className="label mb-3">
        {caption} · <span className="text-accent">{run.run_id}</span>
      </div>
      <dl className="space-y-2">
        <StatRow label="Records processed" value={formatNumber(run.records_processed)} />
        <StatRow
          label="Deterministic matches"
          value={formatNumber(run.deterministic_matches)}
        />
        <StatRow label="Residuals" value={formatNumber(run.residuals)} />
        <StatRow label="Match rate" value={formatPercent(run.match_rate)} />
        <StatRow label="Processing time" value={formatMs(run.processing_time_ms)} />
        <StatRow label="Throughput" value={formatThroughput(run.throughput_rps)} />
        <StatRow
          label="Unexplained value"
          value={formatINR(run.unexplained_value_paisa)}
        />
      </dl>
    </div>
  )
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between text-sm">
      <dt className="text-ink-3">{label}</dt>
      <dd className="num text-ink">{value}</dd>
    </div>
  )
}

function DeltaRow({
  label,
  value,
  sub,
}: {
  label: string
  value: React.ReactNode
  sub?: string
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <dt className="text-ink-3">{label}</dt>
        <dd className="text-md font-semibold">{value}</dd>
      </div>
      {sub ? <div className="num text-right text-xs text-ink-3">{sub}</div> : null}
    </div>
  )
}
