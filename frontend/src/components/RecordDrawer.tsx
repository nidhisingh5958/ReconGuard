/**
 * Reconciliation detail drawer.
 *
 * This answers "why was this matched?" and it is the most important surface in
 * the product. Everything shown is read back from what the engine proved at run
 * time: the arithmetic with real numbers substituted, the source records, the
 * ordered matching layers, and the audit events. Nothing is re-derived in the
 * browser and nothing is generated.
 */

import { useEffect, useState } from 'react'

import { Field, Loading, Money, ReasonCode, StatusBadge } from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { api } from '@/lib/api'
import { formatDateTime, formatINR } from '@/lib/format'
import {
  CONFIDENCE_METHOD_NOTES,
  MATCH_TYPE_LABELS,
  statusStyle,
} from '@/lib/status'
import type { Explanation } from '@/types'

type Tab = 'calculation' | 'evidence' | 'logic' | 'audit'

const TABS: { id: Tab; label: string }[] = [
  { id: 'calculation', label: 'Financial calculation' },
  { id: 'evidence', label: 'Source records & evidence' },
  { id: 'logic', label: 'Matching logic' },
  { id: 'audit', label: 'Audit events' },
]

export function RecordDrawer({
  reconciliationId,
  runId,
  onClose,
}: {
  reconciliationId: string | null
  runId: string | null
  onClose: () => void
}) {
  const [tab, setTab] = useState<Tab>('calculation')

  const { data, loading, error } = useApi(
    () => api.explain(reconciliationId!, runId ?? undefined),
    [reconciliationId, runId],
    { enabled: Boolean(reconciliationId) },
  )
  const detail = useApi(
    () => api.record(reconciliationId!, runId ?? undefined),
    [reconciliationId, runId],
    { enabled: Boolean(reconciliationId) },
  )

  useEffect(() => {
    setTab('calculation')
  }, [reconciliationId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!reconciliationId) return null

  const record = detail.data
  const style = data ? statusStyle(data.status) : null

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        aria-label="Close detail"
        className="flex-1 bg-black/50"
        onClick={onClose}
      />
      <aside className="flex h-full w-full max-w-[860px] flex-col border-l border-line-strong bg-panel shadow-2xl">
        {/* header */}
        <header className="shrink-0 border-b border-line px-5 py-3">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="num text-lg font-semibold text-accent">
                  {reconciliationId}
                </span>
                {data ? <StatusBadge status={data.status} size="md" /> : null}
              </div>
              {data ? (
                <p className="mt-1.5 max-w-[640px] text-sm text-ink-2">{data.verdict}</p>
              ) : null}
            </div>
            <button className="btn shrink-0" onClick={onClose}>
              Close
              <span className="ml-1 text-ink-3">esc</span>
            </button>
          </div>

          {record ? (
            <div className="mt-3 grid grid-cols-2 gap-x-8 gap-y-0 md:grid-cols-3">
              <Field label="Order">
                <span className="num">{record.order_id ?? '—'}</span>
              </Field>
              <Field label="Payment">
                <span className="num">{record.payment_id ?? '—'}</span>
              </Field>
              <Field label="Invoice">
                <span className="num">{record.invoice_id ?? '—'}</span>
              </Field>
              <Field label="Settlements">
                <span className="num">{record.settlement_ids.join(', ') || '—'}</span>
              </Field>
              <Field label="Bank">
                <span className="num">
                  {record.bank_transaction_ids.join(', ') || '—'}
                </span>
              </Field>
              <Field label="Counterparty">{record.counterparty ?? '—'}</Field>
            </div>
          ) : null}

          {/* the money line */}
          {record ? (
            <div className="mt-3 grid grid-cols-4 divide-x divide-line rounded border border-line bg-canvas">
              <AmountCell label="Gross" paisa={record.gross_amount_paisa} />
              <AmountCell label="Expected net" paisa={record.expected_amount_paisa} />
              <AmountCell label="Actual net" paisa={record.actual_amount_paisa} />
              <AmountCell label="Variance" paisa={record.variance_paisa} variance />
            </div>
          ) : null}

          {/* confidence */}
          {data ? (
            <div className="mt-3 flex items-start gap-3 rounded border border-line bg-canvas px-3 py-2">
              <div>
                <div className="label">Confidence</div>
                <div className={`num mt-0.5 text-lg font-semibold ${style?.text}`}>
                  {data.confidence.toFixed(2)}
                </div>
              </div>
              <div className="min-w-0 border-l border-line pl-3">
                <div className="label">
                  {MATCH_TYPE_LABELS[data.match_type] ?? data.match_type} ·{' '}
                  {data.confidence_method}
                </div>
                <p className="mt-0.5 text-xs text-ink-2">
                  {CONFIDENCE_METHOD_NOTES[data.confidence_method] ??
                    'Deterministic rule applied.'}
                </p>
              </div>
            </div>
          ) : null}

          {data && data.reason_codes.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {data.reason_codes.map((code) => (
                <ReasonCode key={code} code={code} />
              ))}
            </div>
          ) : null}
        </header>

        {/* tabs */}
        <nav className="flex shrink-0 gap-0 border-b border-line px-5">
          {TABS.map((item) => (
            <button
              key={item.id}
              onClick={() => setTab(item.id)}
              className={[
                'relative px-3 py-2 text-sm transition-colors',
                tab === item.id
                  ? 'text-ink'
                  : 'text-ink-3 hover:text-ink-2',
              ].join(' ')}
            >
              {item.label}
              {tab === item.id ? (
                <span className="absolute inset-x-2 bottom-0 h-[2px] bg-accent" />
              ) : null}
            </button>
          ))}
        </nav>

        {/* body */}
        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {loading || detail.loading ? <Loading label="Loading evidence" /> : null}
          {error ? <p className="text-sm text-exception">{error}</p> : null}

          {data && tab === 'calculation' ? (
            <CalculationTab data={data} />
          ) : null}
          {data && record && tab === 'evidence' ? (
            <EvidenceTab data={data} sourceRecords={record.source_records} />
          ) : null}
          {data && tab === 'logic' ? <LogicTab data={data} /> : null}
          {data && tab === 'audit' ? <AuditTab data={data} /> : null}
        </div>
      </aside>
    </div>
  )
}

function AmountCell({
  label,
  paisa,
  variance = false,
}: {
  label: string
  paisa: number
  variance?: boolean
}) {
  return (
    <div className="px-3 py-2">
      <div className="label">{label}</div>
      <div className="mt-0.5 text-md">
        <Money paisa={paisa} variance={variance} />
      </div>
    </div>
  )
}

function CalculationTab({ data }: { data: Explanation }) {
  return (
    <div className="space-y-4">
      <section>
        <h3 className="label mb-2">Deterministic derivation</h3>
        {/* A three-column grid rather than a four-column table: the rule id
            rides under its step label so the expression, which is the point of
            the whole panel, gets the full width and never has to be clipped. */}
        <div className="overflow-hidden rounded border border-line">
          <div className="label grid grid-cols-[190px_1fr_120px] gap-3 border-b border-line bg-panel px-3 py-2">
            <span>Step</span>
            <span>Expression (actual values)</span>
            <span className="text-right">Result</span>
          </div>
          {data.financial_calculation.map((line, index) => (
            <div
              key={index}
              className="grid grid-cols-[190px_1fr_120px] items-baseline gap-3 border-b border-line/70 px-3 py-2 last:border-0"
            >
              <div className="min-w-0">
                <div className="truncate text-sm text-ink-2">{line.label}</div>
                <div className="num text-2xs text-accent">{line.rule_id}</div>
              </div>
              <div className="num break-all text-sm text-ink">{line.expression}</div>
              <div className="text-right text-sm">
                <Money paisa={line.result_paisa} />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-3">
          Every expression above is the literal arithmetic the engine executed, with
          real values substituted. Amounts are integer paise throughout.
        </p>
      </section>

      {data.adjustments.length > 0 ? (
        <section>
          <h3 className="label mb-2">Adjustments (netting layer)</h3>
          <div className="space-y-2">
            {data.adjustments.map((adj) => (
              <div key={adj.adjustment_id} className="rounded border border-line bg-canvas p-3">
                <div className="flex items-center justify-between">
                  <span className="chip border-line-strong bg-raised text-ink-2">
                    {adj.type}
                  </span>
                  <Money paisa={adj.amount_paisa} />
                </div>
                <p className="mt-1.5 text-sm text-ink-2">{adj.description}</p>
                <div className="mt-1.5 flex gap-4 text-xs text-ink-3">
                  <span>
                    payment <span className="num">{adj.related_payment ?? '—'}</span>
                  </span>
                  <span>
                    settlement{' '}
                    <span className="num">{adj.related_settlement ?? '—'}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section>
        <h3 className="label mb-2">Rules applied</h3>
        <div className="flex flex-wrap gap-1">
          {data.rules_applied.map((rule) => (
            <span key={rule} className="chip num border-accent/30 bg-accent/10 text-accent">
              {rule}
            </span>
          ))}
        </div>
      </section>
    </div>
  )
}

function EvidenceTab({
  data,
  sourceRecords,
}: {
  data: Explanation
  sourceRecords: string[]
}) {
  return (
    <div className="space-y-4">
      <section>
        <h3 className="label mb-2">Source records ({sourceRecords.length})</h3>
        <div className="flex flex-wrap gap-1">
          {sourceRecords.map((id) => (
            <span key={id} className="chip num border-line-strong bg-raised text-ink">
              {id}
            </span>
          ))}
        </div>
      </section>

      <section>
        <h3 className="label mb-2">Evidence ({data.evidence.length})</h3>
        <div className="space-y-1.5">
          {data.evidence.map((item, index) => (
            <div
              key={index}
              className="rounded border border-line bg-canvas px-3 py-2"
            >
              <div className="flex items-baseline gap-2">
                <span className="chip border-line-strong bg-raised text-2xs text-ink-3">
                  {item.source}
                </span>
                <span className="num text-sm text-accent">{item.record_id}</span>
                {item.amount_paisa !== null ? (
                  <span className="num ml-auto text-sm text-ink-2">
                    {formatINR(item.amount_paisa)}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-ink-2">{item.fact}</p>
              {item.detail && Object.keys(item.detail).length > 0 ? (
                <div className="mt-1 flex flex-wrap gap-x-3 text-2xs text-ink-3">
                  {Object.entries(item.detail).map(([key, value]) => (
                    <span key={key} className="num">
                      {key}={String(value)}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}

function LogicTab({ data }: { data: Explanation }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink-2">{data.question}</p>
      <ol className="relative space-y-0 border-l border-line pl-5">
        {data.matching_logic.map((step, index) => (
          <li key={index} className="relative pb-4 last:pb-0">
            <span className="absolute -left-[23px] top-1.5 h-1.5 w-1.5 rounded-full bg-accent" />
            <div className="label text-accent">{step.layer}</div>
            <p className="mt-0.5 text-sm text-ink-2">{step.detail}</p>
          </li>
        ))}
      </ol>
      <div className="rounded border border-line bg-canvas px-3 py-2 text-xs text-ink-3">
        This explanation is assembled by deterministic retrieval from stored
        evidence ({data.generated_by}). No language model produced any part of it.
      </div>
    </div>
  )
}

function AuditTab({ data }: { data: Explanation }) {
  return (
    <div className="overflow-hidden rounded border border-line">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="th">Timestamp</th>
            <th className="th">Action</th>
            <th className="th">Transition</th>
            <th className="th">Calculation</th>
            <th className="th">Rule</th>
          </tr>
        </thead>
        <tbody>
          {data.audit_events.map((event) => (
            <tr key={event.audit_id} className="border-b border-line/70 last:border-0">
              <td className="td num text-xs text-ink-3">
                {formatDateTime(event.timestamp)}
              </td>
              <td className="td text-xs text-ink">{event.action}</td>
              <td className="td num text-2xs text-ink-2">
                {event.previous_state ? `${event.previous_state} → ` : ''}
                {event.new_state ?? '—'}
              </td>
              <td className="td num max-w-[320px] truncate text-xs" title={event.calculation}>
                {event.calculation || '—'}
              </td>
              <td className="td num text-2xs text-accent">{event.rule_id ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
