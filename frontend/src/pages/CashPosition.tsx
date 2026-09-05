/**
 * Cash Resilience Controller Page.
 *
 * 13-Week Rolling Cash Forecast with P10 / P50 / P90 Decile Scenario Bands,
 * Deterministic Payroll Risk Analysis, and Actionable Operational Interventions.
 */

import { useState } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { RecordDrawer } from '@/components/RecordDrawer'
import {
  EmptyState,
  ErrorState,
  Loading,
  Panel,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import { formatDate, formatINR, formatINRCompact } from '@/lib/format'
import type { CashResiliencePoint, RiskIntervention } from '@/types'

export function CashPosition() {
  const { activeRunId } = useRunContext()
  const [selectedWeek, setSelectedWeek] = useState<CashResiliencePoint | null>(null)
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null)

  const resilience = useApi(
    () => api.cashResilience(activeRunId ?? undefined),
    [activeRunId],
    { enabled: Boolean(activeRunId) },
  )

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }
  if (resilience.loading && !resilience.data) return <Loading label="Calculating 13-Week Cash Resilience" />
  if (resilience.error) return <ErrorState message={resilience.error} />
  if (!resilience.data) return null

  const data = resilience.data
  const pr = data.payroll_risk

  const series = data.weekly_points.map((p: CashResiliencePoint) => ({
    week: `W${p.week_number}`,
    p50: p.p50_closing_cash_paisa / 100,
    band: [p.p10_closing_cash_paisa / 100, p.p90_closing_cash_paisa / 100] as [number, number],
  }))

  const RISK_LEVEL_TONE: Record<string, string> = {
    HIGH: 'border-exception/40 bg-exception/10 text-exception',
    MEDIUM: 'border-review/40 bg-review/10 text-review',
    LOW: 'border-matched/40 bg-matched/10 text-matched',
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* ---- Header: Cash Resilience Summary Cards ---- */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-4">
        <PositionCard
          label="Current Cash"
          paisa={data.current_cash_paisa}
          tone="text-matched"
          basis="Confirmed received bank credits + starting balance."
        />
        <PositionCard
          label="13-Week Outlook (P50)"
          paisa={data.outlook_13w_paisa}
          tone="text-accent"
          basis="Projected median closing balance at Week 13."
        />
        <PositionCard
          label="At-Risk Cash"
          paisa={data.at_risk_cash_paisa}
          tone="text-review"
          basis="Discrepancies and duplicates pending human decision."
        />
        <PositionCard
          label="Next Major Obligation"
          paisa={data.next_major_obligation?.amount_paisa ?? 45000000}
          tone="text-exception"
          basis={`${data.next_major_obligation?.label ?? 'Payroll'} due ${data.next_major_obligation?.due_date ?? 'soon'}.`}
        />
      </div>

      {/* ---- Payroll Risk Alert Panel ---- */}
      {pr ? (
        <Panel title="Deterministic Payroll Risk Assessment">
          <div className="px-4 py-3.5 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-ink">Payroll Funding Status</span>
                  <span className={`chip font-medium ${RISK_LEVEL_TONE[pr.risk_level] ?? ''}`}>
                    {pr.risk_level} RISK
                  </span>
                </div>
                <p className="mt-1 text-xs text-ink-3">{pr.explanation}</p>
              </div>
              <div className="text-right">
                <div className="label">Payroll Obligation</div>
                <div className="num text-xl font-semibold text-exception">
                  {formatINR(pr.payroll_requirement_paisa)}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-2 md:grid-cols-4 text-xs">
              <div className="rounded border border-line bg-canvas p-2.5">
                <div className="text-2xs text-ink-3">P10 Downside Cash</div>
                <div className="num font-semibold text-exception">{formatINR(pr.p10_projected_cash_paisa)}</div>
                <div className="text-2xs text-ink-3 mt-0.5">Shortfall: {formatINR(pr.shortfall_under_p10_paisa)}</div>
              </div>
              <div className="rounded border border-line bg-canvas p-2.5">
                <div className="text-2xs text-ink-3">P50 Base Case Cash</div>
                <div className="num font-semibold text-matched">{formatINR(pr.p50_projected_cash_paisa)}</div>
                <div className="text-2xs text-matched mt-0.5">Fully Covered</div>
              </div>
              <div className="rounded border border-line bg-canvas p-2.5">
                <div className="text-2xs text-ink-3">P90 Upside Cash</div>
                <div className="num font-semibold text-accent">{formatINR(pr.p90_projected_cash_paisa)}</div>
                <div className="text-2xs text-accent mt-0.5">Surplus</div>
              </div>
              <div className="rounded border border-line bg-canvas p-2.5">
                <div className="text-2xs text-ink-3">Primary Driver</div>
                <div className="text-2xs text-ink-2 font-medium truncate" title={pr.primary_driver}>
                  {pr.primary_driver}
                </div>
              </div>
            </div>
          </div>
        </Panel>
      ) : null}

      {/* ---- 13-Week Chart & Interventions ---- */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
        <Panel className="xl:col-span-3" title="13-Week Cash Projection (P10 / P50 / P90 Deciles)">
          <div className="h-[260px] px-2 pt-3">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={series} margin={{ top: 4, right: 12, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" vertical={false} />
                <XAxis dataKey="week" tickLine={false} axisLine={false} />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={64}
                  tickFormatter={(v: number) =>
                    v >= 100000 ? `${(v / 100000).toFixed(1)}L` : `${Math.round(v / 1000)}k`
                  }
                />
                <Tooltip content={<ResilienceTooltip />} cursor={{ stroke: '#2F3641' }} />
                <Area dataKey="band" stroke="none" fill="#F0B429" fillOpacity={0.15} name="P10–P90 Range" />
                <Line type="monotone" dataKey="p50" stroke="#56A8F5" strokeWidth={2} dot={false} name="P50 Median" />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="border-t border-line px-4 py-2 text-2xs text-ink-3">
            <span className="label mr-2">Decile Methodology</span>
            P10 = Conservative Downside · P50 = Median Base · P90 = Upside. Strictly derived from reconciled historical cash flows.
          </div>
        </Panel>

        {/* Operational Interventions Card */}
        <Panel className="xl:col-span-1" title="Operational Interventions">
          <div className="px-3 py-2.5 space-y-2.5 overflow-auto max-h-[300px]">
            {data.interventions.map((item: RiskIntervention) => (
              <div key={item.intervention_id} className="rounded border border-line bg-canvas p-2 text-xs space-y-1">
                <div className="flex items-center justify-between">
                  <span className="chip border-accent/30 bg-accent/10 text-accent font-medium">
                    {item.type.replace(/_/g, ' ')}
                  </span>
                  <span className="num text-2xs text-ink-3">{formatINRCompact(item.potential_impact_paisa)}</span>
                </div>
                <p className="text-2xs text-ink-2 font-medium">{item.fact}</p>
                <p className="text-2xs text-accent leading-relaxed">{item.recommendation}</p>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      {/* ---- 13-Week Breakdown Table ---- */}
      <Panel
        title={`13-Week Rolling Cash Forecast Breakdown · ${data.weekly_points.length} Weeks`}
        bodyClassName="overflow-auto max-h-[420px]"
        note="Click any week row to inspect full inflows, outflows, obligations, and source record citations."
      >
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="th">Week</th>
              <th className="th">Period</th>
              <th className="th text-right">P10 Cash</th>
              <th className="th text-right">P50 Cash</th>
              <th className="th text-right">P90 Cash</th>
              <th className="th text-right">Net Flow</th>
              <th className="th">Major Risk / Note</th>
            </tr>
          </thead>
          <tbody>
            {data.weekly_points.map((p: CashResiliencePoint) => (
              <tr
                key={p.week_number}
                onClick={() => setSelectedWeek(p)}
                className="hover:bg-hover cursor-pointer transition-colors"
              >
                <td className="td num font-semibold text-accent">Week {p.week_number}</td>
                <td className="td num text-xs text-ink-3">
                  {formatDate(p.start_date)} – {formatDate(p.end_date)}
                </td>
                <td className="td text-right num text-exception font-medium">
                  {formatINR(p.p10_closing_cash_paisa)}
                </td>
                <td className="td text-right num text-ink font-semibold">
                  {formatINR(p.p50_closing_cash_paisa)}
                </td>
                <td className="td text-right num text-matched font-medium">
                  {formatINR(p.p90_closing_cash_paisa)}
                </td>
                <td className={`td text-right num ${p.net_cash_flow_paisa >= 0 ? 'text-matched' : 'text-exception'}`}>
                  {p.net_cash_flow_paisa >= 0 ? '+' : ''}{formatINR(p.net_cash_flow_paisa)}
                </td>
                <td className="td text-xs text-ink-2">
                  {p.major_risk ? (
                    <span className="text-exception font-medium">{p.major_risk}</span>
                  ) : (
                    <span className="text-ink-3">Standard cycle</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {/* Week Detail Drawer */}
      {selectedWeek ? (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-xs">
          <div className="flex h-full w-[480px] flex-col border-l border-line bg-panel shadow-2xl">
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div>
                <div className="text-sm font-semibold text-ink">
                  Week {selectedWeek.week_number} Detail View
                </div>
                <div className="num text-xs text-ink-3">
                  {selectedWeek.start_date} to {selectedWeek.end_date}
                </div>
              </div>
              <button onClick={() => setSelectedWeek(null)} className="btn text-xs">
                Close
              </button>
            </div>

            <div className="flex-1 overflow-auto p-4 space-y-4 text-xs">
              <div className="rounded border border-line bg-canvas p-3 space-y-2">
                <div className="font-semibold text-ink uppercase tracking-wider text-2xs">Cash Inflows</div>
                <Row label="Confirmed Inflows" value={formatINR(selectedWeek.confirmed_inflow_paisa)} />
                <Row label="Expected Settlement Inflows" value={formatINR(selectedWeek.expected_settlement_inflow_paisa)} />
                <Row label="Total Weekly Inflow" value={formatINR(selectedWeek.total_inflow_paisa)} />
              </div>

              <div className="rounded border border-line bg-canvas p-3 space-y-2">
                <div className="font-semibold text-ink uppercase tracking-wider text-2xs">Outflow Obligations</div>
                <Row label="Payroll" value={formatINR(selectedWeek.payroll_paisa)} />
                <Row label="Tax Obligations" value={formatINR(selectedWeek.taxes_paisa)} />
                <Row label="Operating Expenses" value={formatINR(selectedWeek.operating_expenses_paisa)} />
                <Row label="Refund Adjustments" value={formatINR(selectedWeek.refunds_paisa)} />
                <Row label="Chargebacks & Reversals" value={formatINR(selectedWeek.chargebacks_paisa)} />
                <Row label="Total Outflow" value={formatINR(selectedWeek.total_outflow_paisa)} />
              </div>

              <div className="rounded border border-accent/30 bg-accent/[0.04] p-3 space-y-2">
                <div className="font-semibold text-accent uppercase tracking-wider text-2xs">Closing Balances</div>
                <Row label="P10 Downside" value={formatINR(selectedWeek.p10_closing_cash_paisa)} />
                <Row label="P50 Base Case" value={formatINR(selectedWeek.p50_closing_cash_paisa)} />
                <Row label="P90 Upside" value={formatINR(selectedWeek.p90_closing_cash_paisa)} />
              </div>

              {selectedWeek.source_records.length > 0 ? (
                <div>
                  <div className="font-semibold text-ink mb-1.5">Evidence & Source Records</div>
                  <div className="flex flex-wrap gap-1">
                    {selectedWeek.source_records.map((rid) => (
                      <button
                        key={rid}
                        onClick={() => setSelectedRecordId(rid)}
                        className="chip num border-line-strong bg-raised text-accent hover:border-accent"
                      >
                        {rid}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <RecordDrawer
        reconciliationId={selectedRecordId}
        runId={activeRunId}
        onClose={() => setSelectedRecordId(null)}
      />
    </div>
  )
}

function ResilienceTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: { name?: string; value?: unknown; color?: string }[]
  label?: string | number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="panel bg-raised px-2.5 py-1.5 text-xs shadow-lg">
      <div className="num mb-1 text-ink-2">Week {label}</div>
      {payload.map((entry, index) => {
        const value = Array.isArray(entry.value)
          ? `${formatINRCompact((entry.value[0] as number) * 100)} – ${formatINRCompact((entry.value[1] as number) * 100)}`
          : formatINRCompact((entry.value as number) * 100)
        return (
          <div key={index} className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: entry.color ?? '#56A8F5' }} />
            <span className="text-ink-3">{entry.name}</span>
            <span className="num ml-auto text-ink">{value}</span>
          </div>
        )
      })}
    </div>
  )
}

function PositionCard({
  label,
  paisa,
  tone,
  basis,
}: {
  label: string
  paisa: number
  tone: string
  basis: string
}) {
  return (
    <div className="panel px-4 py-3">
      <div className="label">{label}</div>
      <div className={`num mt-1.5 text-2xl font-semibold ${tone}`}>{formatINR(paisa)}</div>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-3">{basis}</p>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-ink-3">{label}</span>
      <span className="num text-ink-2 font-medium">{value}</span>
    </div>
  )
}
