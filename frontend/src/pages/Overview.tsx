/**
 * Overview: the state of the last reconciliation run at a glance.
 *
 * Two figures are given equal weight on purpose. TOTAL RECONCILED VALUE is the
 * money the engine can prove; UNEXPLAINED VALUE is the money it cannot. A
 * dashboard that shows only the first is the kind of dashboard this product
 * exists to replace.
 */

import { useNavigate } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  EmptyState,
  ErrorState,
  Loading,
  Metric,
  Money,
  Panel,
  StatusBadge,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import {
  formatINRCompact,
  formatMs,
  formatNumber,
  formatPercent,
  formatThroughput,
  formatDateTime,
} from '@/lib/format'
import { INFORMATIONAL_CODES, STATUS_ORDER, statusStyle } from '@/lib/status'

export function Overview() {
  const { activeRunId, startRun, running } = useRunContext()
  const navigate = useNavigate()
  const { data, error, loading } = useApi(
    () => api.metrics(activeRunId ?? undefined),
    [activeRunId],
  )

  if (loading) return <Loading label="Loading metrics" />
  if (error) return <ErrorState message={error} />

  const run = data?.run
  if (!run) {
    return (
      <EmptyState
        title="No reconciliation run yet"
        detail="Generate the seed dataset and run the deterministic engine to populate the control centre."
        action={
          <button className="btn-accent mt-2" onClick={() => void startRun()} disabled={running}>
            {running ? 'Running…' : 'Run reconciliation'}
          </button>
        }
      />
    )
  }

  const distribution = STATUS_ORDER.map((status) => ({
    status,
    label: statusStyle(status).label,
    count: data?.status_distribution?.[status] ?? 0,
    fill: statusStyle(status).hex,
  }))

  const daily = (data?.daily_volume ?? []).map((d) => ({
    date: d.date.slice(5),
    matched: d.matched,
    residual: d.residual,
  }))

  const reasonCodes = Object.entries(data?.reason_code_distribution ?? {})
  const maxReasonCount = Math.max(1, ...reasonCodes.map(([, count]) => count))

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* ---- headline metrics ---- */}
      <div className="panel grid grid-cols-2 divide-x divide-line lg:grid-cols-4 xl:grid-cols-8">
        <Metric
          label="Total transactions"
          value={formatNumber(run.records_processed)}
          sub={`${formatNumber(run.total_source_records)} source rows`}
        />
        <Metric
          label="Match rate"
          value={formatPercent(run.match_rate)}
          tone="good"
          sub="matched / processed"
          formula="match_rate = deterministic_matches / records_processed"
        />
        <Metric
          label="Deterministic matches"
          value={formatNumber(run.deterministic_matches)}
          sub="proved, confidence 1.00"
        />
        <Metric
          label="Exceptions"
          value={formatNumber(run.exceptions + run.unresolved)}
          tone={run.exceptions + run.unresolved > 0 ? 'bad' : 'default'}
          sub={`${formatPercent(run.exception_rate)} exception rate`}
        />
        <Metric
          label="Processing time"
          value={formatMs(run.processing_time_ms)}
          sub="measured, not estimated"
        />
        <Metric
          label="Throughput"
          value={formatThroughput(run.throughput_rps)}
          sub="records / second"
          formula="throughput = records_processed / processing_time_seconds"
        />
        <Metric
          label="Total reconciled value"
          value={formatINRCompact(run.total_reconciled_paisa)}
          tone="good"
          sub="proved to the paisa"
        />
        <Metric
          label="Unexplained value"
          value={formatINRCompact(run.unexplained_value_paisa)}
          tone={run.unexplained_value_paisa > 0 ? 'bad' : 'good'}
          sub="awaiting human review"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        {/* ---- status distribution ---- */}
        <Panel title="Reconciliation status distribution" className="xl:col-span-1">
          <div className="divide-y divide-line/70">
            {distribution.map((item) => {
              const share = run.records_processed
                ? item.count / run.records_processed
                : 0
              return (
                <button
                  key={item.status}
                  onClick={() =>
                    navigate(`/reconciliation?status=${item.status}`)
                  }
                  className="row flex w-full items-center gap-3 px-3 py-2 text-left"
                >
                  <StatusBadge status={item.status} />
                  <div className="ml-auto flex items-center gap-3">
                    <div className="h-1 w-24 rounded-sm bg-line">
                      <div
                        className="h-1 rounded-sm"
                        style={{
                          width: `${Math.max(share * 100, item.count > 0 ? 2 : 0)}%`,
                          backgroundColor: item.fill,
                        }}
                      />
                    </div>
                    <span className="num w-12 text-right text-sm">{item.count}</span>
                    <span className="num w-14 text-right text-xs text-ink-3">
                      {formatPercent(share, 1)}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </Panel>

        {/* ---- daily volume ---- */}
        <Panel title="Daily settlement volume" className="xl:col-span-2">
          <div className="h-[218px] px-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={daily} margin={{ top: 4, right: 12, left: -18, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="date" tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis tickLine={false} axisLine={false} width={40} />
                <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#2F3641' }} />
                <Line
                  type="monotone"
                  dataKey="matched"
                  stroke="#3FCF8E"
                  strokeWidth={1.5}
                  dot={false}
                  name="Matched"
                />
                <Line
                  type="monotone"
                  dataKey="residual"
                  stroke="#FF6B6B"
                  strokeWidth={1.5}
                  dot={false}
                  name="Residual"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        {/* ---- reason codes ----
            A ranked list rather than a bar chart: a horizontal bar chart drops
            y-axis labels when categories do not fit, and a reason code with no
            label is useless. The list always shows every code in full. */}
        <Panel
          title="Reason codes raised"
          className="xl:col-span-1"
          note="Grey codes explain how a match was proved; red codes need a human."
          bodyClassName="overflow-auto max-h-[240px]"
        >
          <div className="divide-y divide-line/70">
            {reasonCodes.map(([code, count]) => {
              const informational = INFORMATIONAL_CODES.has(code)
              const share = maxReasonCount ? count / maxReasonCount : 0
              return (
                <button
                  key={code}
                  onClick={() =>
                    navigate(`/exceptions?reason_code=${code}`)
                  }
                  className="row flex w-full items-center gap-3 px-3 py-1.5 text-left"
                >
                  <span
                    className={`w-[164px] shrink-0 truncate text-xs ${
                      informational ? 'text-ink-2' : 'text-exception'
                    }`}
                    title={code}
                  >
                    {code.replace(/_/g, ' ').toLowerCase()}
                  </span>
                  <div className="h-1 flex-1 rounded-sm bg-line">
                    <div
                      className={`h-1 rounded-sm ${
                        informational ? 'bg-ink-3' : 'bg-exception'
                      }`}
                      style={{ width: `${Math.max(share * 100, 3)}%` }}
                    />
                  </div>
                  <span className="num w-7 shrink-0 text-right text-sm">{count}</span>
                </button>
              )
            })}
          </div>
        </Panel>

        {/* ---- recent runs ---- */}
        <Panel
          title="Recent reconciliation runs"
          className="xl:col-span-2"
          actions={
            <button
              className="text-xs text-accent hover:underline"
              onClick={() => navigate('/reconciliation?tab=runs')}
            >
              Compare runs →
            </button>
          }
        >
          <div className="overflow-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="th">Run</th>
                  <th className="th">Dataset</th>
                  <th className="th text-right">Records</th>
                  <th className="th text-right">Matched</th>
                  <th className="th text-right">Residuals</th>
                  <th className="th text-right">Match rate</th>
                  <th className="th text-right">Time</th>
                  <th className="th text-right">Throughput</th>
                  <th className="th">Completed</th>
                </tr>
              </thead>
              <tbody>
                {(data?.recent_runs ?? []).map((r) => (
                  <tr key={r.run_id} className="row">
                    <td className="td num text-accent">{r.run_id}</td>
                    <td className="td text-ink-2">
                      {r.dataset_id}
                      <span className="ml-1.5 text-ink-3">({r.dataset_mode})</span>
                    </td>
                    <td className="td num text-right">{formatNumber(r.records_processed)}</td>
                    <td className="td num text-right text-matched">
                      {formatNumber(r.deterministic_matches)}
                    </td>
                    <td className="td num text-right text-review">
                      {formatNumber(r.residuals)}
                    </td>
                    <td className="td num text-right">{formatPercent(r.match_rate)}</td>
                    <td className="td num text-right text-ink-2">
                      {formatMs(r.processing_time_ms)}
                    </td>
                    <td className="td num text-right text-ink-2">
                      {formatThroughput(r.throughput_rps)}
                    </td>
                    <td className="td text-xs text-ink-3">
                      {formatDateTime(r.completed_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      {/* ---- largest unexplained ---- */}
      <Panel
        title="Largest unexplained value"
        note="Ranked by money the engine could not account for. Nothing here has been auto-resolved."
      >
        <div className="overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th">Status</th>
                <th className="th">Reconciliation</th>
                <th className="th">Counterparty</th>
                <th className="th">Reason codes</th>
                <th className="th text-right">Expected</th>
                <th className="th text-right">Actual</th>
                <th className="th text-right">Unexplained</th>
              </tr>
            </thead>
            <tbody>
              {(data?.top_exceptions_by_value ?? []).map((r) => (
                <tr
                  key={r.reconciliation_id}
                  className="row"
                  onClick={() => navigate(`/exceptions?focus=${r.reconciliation_id}`)}
                >
                  <td className="td">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="td num text-accent">{r.reconciliation_id}</td>
                  <td className="td text-ink-2">{r.counterparty ?? '—'}</td>
                  <td className="td text-xs text-ink-3">
                    {r.reason_codes.join(', ').replace(/_/g, ' ').toLowerCase() || '—'}
                  </td>
                  <td className="td text-right">
                    <Money paisa={r.expected_amount_paisa} muted />
                  </td>
                  <td className="td text-right">
                    <Money paisa={r.actual_amount_paisa} muted />
                  </td>
                  <td className="td text-right">
                    <Money paisa={r.unexplained_value_paisa} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: { name?: string; value?: number | string; color?: string }[]
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="panel bg-raised px-2.5 py-1.5 text-xs shadow-lg">
      <div className="num mb-1 text-ink-2">{label}</div>
      {payload.map((entry, index) => (
        <div key={index} className="flex items-center gap-2">
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-ink-3">{entry.name}</span>
          <span className="num ml-auto text-ink">{entry.value}</span>
        </div>
      ))}
    </div>
  )
}
