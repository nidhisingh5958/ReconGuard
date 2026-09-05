/**
 * Audit trail: chronological, filterable, expandable.
 *
 * Each row expands to the exact calculation, the source records and the state
 * transition. This is the surface an auditor uses to answer "on what basis did
 * this system change its mind about this money?".
 */

import { Fragment, useState } from 'react'

import {
  EmptyState,
  ErrorState,
  Loading,
  Panel,
  StatusBadge,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import { formatDateTime, formatNumber } from '@/lib/format'

const PAGE_SIZE = 150

const ACTION_TONE: Record<string, string> = {
  RECONCILIATION_MATCH: 'text-matched',
  RECONCILIATION_PARTIAL: 'text-partial',
  RECONCILIATION_EXCEPTION: 'text-exception',
  RECONCILIATION_DUPLICATE: 'text-duplicate',
  INVARIANT_VERIFIED: 'text-matched',
  INVARIANT_VIOLATED: 'text-exception',
  ADJUSTMENT_RECORDED: 'text-review',
  RUN_STARTED: 'text-accent',
  RUN_COMPLETED: 'text-accent',
  DATA_INGESTED: 'text-ink-2',
}

export function AuditTrail() {
  const { activeRunId } = useRunContext()
  const [expanded, setExpanded] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const [ruleId, setRuleId] = useState('')
  const [newState, setNewState] = useState('')
  const [reconciliationId, setReconciliationId] = useState('')
  const [sourceRecord, setSourceRecord] = useState('')

  const { data, error, loading } = useApi(
    () =>
      api.audit({
        run_id: activeRunId ?? undefined,
        action: action || undefined,
        rule_id: ruleId || undefined,
        new_state: newState || undefined,
        reconciliation_id: reconciliationId || undefined,
        source_record: sourceRecord || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    [activeRunId, action, ruleId, newState, reconciliationId, sourceRecord, offset],
    { enabled: Boolean(activeRunId) },
  )

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }

  const reset = () => {
    setAction('')
    setRuleId('')
    setNewState('')
    setReconciliationId('')
    setSourceRecord('')
    setOffset(0)
  }

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Panel
        className="min-h-0 flex-1"
        bodyClassName="flex flex-col min-h-0"
        title={`Audit events${data ? ` · ${formatNumber(data.total)}` : ''}`}
        actions={
          <button className="text-xs text-ink-3 hover:text-ink" onClick={reset}>
            Clear filters
          </button>
        }
      >
        {/* filter bar */}
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <select
            className="input"
            value={action}
            onChange={(e) => {
              setAction(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">All actions</option>
            {(data?.facets.actions ?? []).map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <select
            className="input num"
            value={ruleId}
            onChange={(e) => {
              setRuleId(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">All rules</option>
            {(data?.facets.rule_ids ?? []).map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={newState}
            onChange={(e) => {
              setNewState(e.target.value)
              setOffset(0)
            }}
          >
            <option value="">All statuses</option>
            {['MATCHED', 'PARTIAL_MATCH', 'REVIEW_REQUIRED', 'DUPLICATE', 'EXCEPTION'].map(
              (s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ),
            )}
          </select>
          <input
            className="input num w-36"
            placeholder="REC-00001"
            value={reconciliationId}
            onChange={(e) => {
              setReconciliationId(e.target.value)
              setOffset(0)
            }}
          />
          <input
            className="input num w-40"
            placeholder="Source record id"
            value={sourceRecord}
            onChange={(e) => {
              setSourceRecord(e.target.value)
              setOffset(0)
            }}
          />
        </div>

        {loading ? <Loading label="Loading audit events" /> : null}
        {error ? <ErrorState message={error} /> : null}

        {data && !loading ? (
          <>
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="th w-[150px]">Timestamp</th>
                    <th className="th w-[200px]">Action</th>
                    <th className="th w-[110px]">Reconciliation</th>
                    <th className="th w-[130px]">Transition</th>
                    <th className="th">Calculation</th>
                    <th className="th w-[110px]">Rule</th>
                    <th className="th w-[90px]">Actor</th>
                  </tr>
                </thead>
                <tbody>
                  {data.events.map((event) => {
                    const isOpen = expanded === event.audit_id
                    return (
                      <Fragment key={event.audit_id}>
                        <tr
                          className="row"
                          onClick={() => setExpanded(isOpen ? null : event.audit_id)}
                        >
                          <td className="td num text-xs text-ink-3">
                            {formatDateTime(event.timestamp)}
                          </td>
                          <td className="td">
                            <span
                              className={`text-xs ${ACTION_TONE[event.action] ?? 'text-ink-2'}`}
                            >
                              {isOpen ? '▾' : '▸'} {event.action}
                            </span>
                          </td>
                          <td className="td num text-xs text-accent">
                            {event.reconciliation_id ?? '—'}
                          </td>
                          <td className="td">
                            {event.new_state ? (
                              <StatusBadge status={event.new_state} />
                            ) : (
                              <span className="text-xs text-ink-3">—</span>
                            )}
                          </td>
                          <td
                            className="td num max-w-0 truncate text-xs"
                            title={event.calculation}
                          >
                            {event.calculation || '—'}
                          </td>
                          <td className="td num text-2xs text-accent">
                            {event.rule_id ?? '—'}
                          </td>
                          <td className="td text-2xs text-ink-3">{event.actor}</td>
                        </tr>
                        {isOpen ? (
                          <tr>
                            <td colSpan={7} className="border-b border-line bg-canvas p-0">
                              <div className="grid grid-cols-1 gap-4 px-4 py-3 lg:grid-cols-3">
                                <div>
                                  <div className="label mb-1">Exact calculation</div>
                                  <pre className="num whitespace-pre-wrap break-all rounded border border-line bg-panel px-2 py-1.5 text-xs text-ink">
                                    {event.calculation || 'no calculation recorded'}
                                  </pre>
                                  <div className="mt-2 flex gap-4 text-2xs text-ink-3">
                                    <span className="num">{event.audit_id}</span>
                                    <span className="num">{event.system_version}</span>
                                  </div>
                                </div>
                                <div>
                                  <div className="label mb-1">
                                    Source records ({event.source_records.length})
                                  </div>
                                  <div className="flex flex-wrap gap-1">
                                    {event.source_records.map((id) => (
                                      <span
                                        key={id}
                                        className="chip num border-line-strong bg-panel text-ink-2"
                                      >
                                        {id}
                                      </span>
                                    ))}
                                    {event.source_records.length === 0 ? (
                                      <span className="text-xs text-ink-3">—</span>
                                    ) : null}
                                  </div>
                                </div>
                                <div>
                                  <div className="label mb-1">Detail</div>
                                  <dl className="space-y-0.5">
                                    {Object.entries(event.detail).map(([key, value]) => (
                                      <div
                                        key={key}
                                        className="flex items-baseline justify-between gap-3 text-xs"
                                      >
                                        <dt className="text-ink-3">{key}</dt>
                                        <dd className="num max-w-[220px] truncate text-right text-ink-2">
                                          {typeof value === 'object'
                                            ? JSON.stringify(value)
                                            : String(value)}
                                        </dd>
                                      </div>
                                    ))}
                                  </dl>
                                </div>
                              </div>
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    )
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex shrink-0 items-center justify-between border-t border-line px-3 py-2 text-xs text-ink-3">
              <span className="num">
                {data.total === 0 ? 0 : offset + 1}–
                {Math.min(offset + PAGE_SIZE, data.total)} of {formatNumber(data.total)}
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
    </div>
  )
}
