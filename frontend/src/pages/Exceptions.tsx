/**
 * The Honest Exception List.
 *
 * The product rule this page enforces: an exception states what could NOT be
 * established, and its resolution status stays HUMAN REVIEW REQUIRED. There is
 * no "suggested fix", no auto-clear, and no confidence score invented to make
 * an unknown look handled. That restraint is the feature.
 */

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { RecordDrawer } from '@/components/RecordDrawer'
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
import { formatDate, formatINR, formatNumber } from '@/lib/format'

export function Exceptions() {
  const { activeRunId } = useRunContext()
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<string | null>(params.get('focus'))

  const reasonCode = params.get('reason_code') ?? ''

  const { data, error, loading } = useApi(
    () =>
      api.exceptions({
        run_id: activeRunId ?? undefined,
        reason_code: reasonCode || undefined,
        limit: 300,
      }),
    [activeRunId, reasonCode],
    { enabled: Boolean(activeRunId) },
  )

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }
  if (loading) return <Loading label="Loading exceptions" />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  const summary = data.summary
  const byReason = Object.entries(summary?.by_reason_code ?? {})

  const setReason = (code: string) => {
    const next = new URLSearchParams(params)
    if (code) next.set('reason_code', code)
    else next.delete('reason_code')
    setParams(next)
  }

  return (
    <div className="flex h-full gap-3 p-3">
      {/* ---- left rail: exception classes ---- */}
      <div className="flex w-[280px] shrink-0 flex-col gap-3">
        <Panel title="Exception desk">
          <div className="px-4 py-3">
            <div className="label">Items requiring review</div>
            <div className="num mt-1 text-3xl font-semibold text-exception">
              {formatNumber(summary?.total ?? 0)}
            </div>
            <div className="mt-3 space-y-2 border-t border-line pt-3">
              <div>
                <div className="label">Total at stake</div>
                <div className="num mt-0.5 text-xl font-semibold">
                  {formatINR(summary?.total_value_paisa ?? 0)}
                </div>
              </div>
              <div>
                <div className="label">Of which unexplained</div>
                <div className="num mt-0.5 text-md font-semibold text-exception">
                  {formatINR(summary?.unexplained_value_paisa ?? 0)}
                </div>
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="By reason code" className="min-h-0 flex-1" bodyClassName="overflow-auto">
          <button
            onClick={() => setReason('')}
            className={`row flex w-full items-baseline justify-between border-b border-line/70 px-3 py-2 text-left text-sm ${
              reasonCode === '' ? 'bg-accent/[0.07] text-accent' : 'text-ink-2'
            }`}
          >
            <span>All exceptions</span>
            <span className="num">{summary?.total ?? 0}</span>
          </button>
          {byReason.map(([code, stats]) => (
            <button
              key={code}
              onClick={() => setReason(code)}
              className={`row flex w-full flex-col items-start gap-0.5 border-b border-line/70 px-3 py-2 text-left ${
                reasonCode === code ? 'bg-accent/[0.07]' : ''
              }`}
            >
              <div className="flex w-full items-baseline justify-between">
                <span
                  className={`text-sm ${reasonCode === code ? 'text-accent' : 'text-ink-2'}`}
                >
                  {code.replace(/_/g, ' ').toLowerCase()}
                </span>
                <span className="num text-sm">{stats.count}</span>
              </div>
              <span className="num text-2xs text-ink-3">
                {formatINR(stats.value_paisa)}
              </span>
            </button>
          ))}
        </Panel>
      </div>

      {/* ---- exception cards ---- */}
      <div className="min-h-0 flex-1 overflow-auto">
        {data.exceptions.length === 0 ? (
          <Panel>
            <EmptyState
              title="No exceptions in this run"
              detail="Every record reconciled to a proved counterpart."
            />
          </Panel>
        ) : (
          <div className="grid grid-cols-1 gap-2 2xl:grid-cols-2">
            {data.exceptions.map((item) => (
              <article
                key={item.reconciliation_id}
                onClick={() => setSelected(item.reconciliation_id)}
                className="panel cursor-pointer p-0 transition-colors hover:border-line-strong"
              >
                <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-2.5">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="num text-md font-semibold text-accent">
                        {item.reconciliation_id}
                      </span>
                      <StatusBadge status={item.status} />
                    </div>
                    <div className="mt-0.5 text-sm text-ink">{item.headline}</div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div
                      className={`num text-lg font-semibold ${
                        item.status === 'PARTIAL_MATCH'
                          ? 'text-partial'
                          : 'text-exception'
                      }`}
                    >
                      {formatINR(item.exposure_paisa)}
                    </div>
                    <div className="text-2xs text-ink-3">
                      {item.status === 'PARTIAL_MATCH' ? 'cash awaited' : 'at stake'}
                    </div>
                  </div>
                </div>

                <div className="px-4 py-2.5">
                  <div className="label mb-1.5">What could not be established</div>
                  <ul className="space-y-0.5">
                    {item.findings.map((finding, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-2 text-sm text-ink-2"
                      >
                        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-exception" />
                        {finding}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-2">
                  <div className="flex gap-4 text-2xs text-ink-3">
                    {item.order_id ? (
                      <span className="num">{item.order_id}</span>
                    ) : null}
                    {item.counterparty ? <span>{item.counterparty}</span> : null}
                    {item.value_date ? (
                      <span className="num">{formatDate(item.value_date)}</span>
                    ) : null}
                    <span className="num">{item.evidence_count} evidence</span>
                  </div>
                  <span className="chip border-exception/40 bg-exception/10 font-semibold text-exception">
                    {item.resolution_status}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <RecordDrawer
        reconciliationId={selected}
        runId={activeRunId}
        onClose={() => setSelected(null)}
      />
    </div>
  )
}
