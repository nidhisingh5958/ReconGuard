/**
 * Journal: proposed corrections and the posted ledger.
 *
 * Nothing an arbitrator produces posts itself. Every entry starts PROPOSED and
 * needs an explicit, attributed decision. The buttons enforce that order:
 * Post is unavailable until an entry is approved, and no action is available
 * until the operator has said who they are.
 *
 * The trial balance shows POSTED entries only. Including proposals would make
 * it a wish rather than a balance.
 */

import { useState } from 'react'

import {
  EmptyState,
  ErrorState,
  Loading,
  Money,
  Panel,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import { formatDate, formatINR, formatNumber } from '@/lib/format'
import type { JournalEntry } from '@/types'

const STATUS_TONE: Record<string, string> = {
  PROPOSED: 'border-review/30 bg-review/10 text-review',
  APPROVED: 'border-partial/30 bg-partial/10 text-partial',
  POSTED: 'border-matched/30 bg-matched/10 text-matched',
  REJECTED: 'border-exception/30 bg-exception/10 text-exception',
  DRAFT: 'border-line-strong bg-raised text-ink-3',
}

export function Journal() {
  const { activeRunId } = useRunContext()
  const [actor, setActor] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const journal = useApi(
    () =>
      api.journal({
        run_id: activeRunId ?? undefined,
        status: status || undefined,
        limit: 500,
      }),
    [activeRunId, status],
    { enabled: Boolean(activeRunId) },
  )
  const balance = useApi(
    () => api.trialBalance(activeRunId ?? undefined),
    [activeRunId, busy],
    { enabled: Boolean(activeRunId) },
  )

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }
  if (journal.loading && !journal.data) return <Loading label="Loading journal" />
  if (journal.error) return <ErrorState message={journal.error} />
  if (!journal.data) return null

  const decide = async (
    entry: JournalEntry,
    decision: 'APPROVE' | 'REJECT' | 'POST',
  ) => {
    setBusy(entry.journal_id)
    setMessage(null)
    try {
      await api.decideJournal(entry.journal_id, decision, actor)
      journal.refetch()
      balance.refetch()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Decision failed')
    } finally {
      setBusy(null)
    }
  }

  const counts = journal.data.by_status
  const trial = balance.data

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="panel grid grid-cols-2 divide-x divide-line md:grid-cols-5">
        <Cell label="Proposed" value={formatNumber(counts.PROPOSED ?? 0)} tone="text-review" />
        <Cell label="Approved" value={formatNumber(counts.APPROVED ?? 0)} tone="text-partial" />
        <Cell label="Posted" value={formatNumber(counts.POSTED ?? 0)} tone="text-matched" />
        <Cell label="Rejected" value={formatNumber(counts.REJECTED ?? 0)} tone="text-exception" />
        <Cell
          label="Proposed value"
          value={formatINR(journal.data.total_proposed_paisa)}
        />
      </div>

      {message ? (
        <div className="panel border-exception/40 bg-exception/[0.07] px-4 py-2 text-sm text-exception">
          {message}
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
        <Panel
          className="xl:col-span-3"
          bodyClassName="overflow-auto max-h-[620px]"
          title={`Journal entries · ${journal.data.total}`}
          note="Every entry is a double-entry pair whose total equals the exact amount the engine could not explain. Amounts are never chosen by an arbitrator."
          actions={
            <div className="flex items-center gap-2">
              <input
                className="input w-52"
                placeholder="Acting as (required)"
                value={actor}
                onChange={(e) => setActor(e.target.value)}
              />
              <select
                className="input"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="">All statuses</option>
                {['PROPOSED', 'APPROVED', 'POSTED', 'REJECTED'].map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
          }
        >
          {journal.data.entries.length === 0 ? (
            <EmptyState
              title="No journal entries for this run"
              detail="Run arbitration on the Copilot page to produce proposals from the residuals."
            />
          ) : (
            <table className="w-full min-w-[1180px] border-collapse">
              <thead>
                <tr>
                  <th className="th w-[86px]">Status</th>
                  <th className="th">Residual</th>
                  <th className="th">Date</th>
                  <th className="th">Debit</th>
                  <th className="th">Credit</th>
                  <th className="th text-right">Amount</th>
                  <th className="th">Narrative</th>
                  <th className="th w-[230px]">Decision</th>
                </tr>
              </thead>
              <tbody>
                {journal.data.entries.map((entry) => (
                  <tr key={entry.journal_id} className="hover:bg-hover">
                    <td className="td">
                      <span className={`chip ${STATUS_TONE[entry.status] ?? ''}`}>
                        {entry.status.toLowerCase()}
                      </span>
                    </td>
                    <td className="td num text-accent">{entry.residual_id}</td>
                    <td className="td num text-xs text-ink-3">
                      {formatDate(entry.entry_date)}
                    </td>
                    <td className="td text-xs">
                      <span className="num text-ink-2">{entry.debit_account}</span>{' '}
                      <span className="text-ink-3">{entry.debit_account_name}</span>
                    </td>
                    <td className="td text-xs">
                      <span className="num text-ink-2">{entry.credit_account}</span>{' '}
                      <span className="text-ink-3">{entry.credit_account_name}</span>
                    </td>
                    <td className="td text-right">
                      <Money paisa={entry.amount_paisa} />
                    </td>
                    <td
                      className="td max-w-[200px] truncate text-xs text-ink-2"
                      title={entry.description}
                    >
                      {entry.description}
                    </td>
                    <td className="td">
                      {entry.status === 'POSTED' || entry.status === 'REJECTED' ? (
                        <span className="text-2xs text-ink-3">
                          {entry.decided_by ?? 'system'}
                        </span>
                      ) : (
                        <div className="flex gap-1 whitespace-nowrap">
                          <button
                            className="btn h-6 px-2"
                            disabled={
                              !actor.trim() ||
                              busy !== null ||
                              entry.status !== 'PROPOSED'
                            }
                            title={
                              !actor.trim()
                                ? 'Enter who is acting: ledger changes are attributed'
                                : 'Approve this correction'
                            }
                            onClick={() => decide(entry, 'APPROVE')}
                          >
                            Approve
                          </button>
                          <button
                            className="btn-accent h-6 px-2"
                            disabled={
                              !actor.trim() ||
                              busy !== null ||
                              entry.status !== 'APPROVED'
                            }
                            title={
                              entry.status !== 'APPROVED'
                                ? 'An entry must be approved before it can be posted'
                                : 'Post to the ledger; the batch is re-verified first'
                            }
                            onClick={() => decide(entry, 'POST')}
                          >
                            Post
                          </button>
                          <button
                            className="btn h-6 px-2"
                            disabled={!actor.trim() || busy !== null}
                            onClick={() => decide(entry, 'REJECT')}
                          >
                            Reject
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <div className="flex flex-col gap-3 xl:col-span-1">
          <Panel
            title="Trial balance"
            note="POSTED entries only. Proposals are excluded by design."
          >
            {trial ? (
              <div className="px-4 py-3">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="text-ink-3">Posted entries</span>
                  <span className="num">{trial.posted_entries}</span>
                </div>
                <div className="mt-2 space-y-1 border-t border-line pt-2 text-sm">
                  <div className="flex items-baseline justify-between">
                    <span className="text-ink-3">Total debits</span>
                    <span className="num">{formatINR(trial.total_debits_paisa)}</span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-ink-3">Total credits</span>
                    <span className="num">{formatINR(trial.total_credits_paisa)}</span>
                  </div>
                </div>
                <div
                  className={`chip mt-3 w-full justify-center ${
                    trial.balanced
                      ? 'border-matched/30 bg-matched/10 text-matched'
                      : 'border-exception/40 bg-exception/10 text-exception'
                  }`}
                >
                  {trial.balanced ? 'BALANCED' : 'OUT OF BALANCE'}
                </div>
              </div>
            ) : (
              <Loading />
            )}
          </Panel>

          {trial && trial.accounts.length > 0 ? (
            <Panel title="Account balances" bodyClassName="overflow-auto max-h-[300px]">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="th">Account</th>
                    <th className="th text-right">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {trial.accounts.map((a: { code: string; name: string; debit_paisa: number; credit_paisa: number; balance_paisa: number }) => (
                    <tr key={a.code} className="hover:bg-hover">
                      <td className="td text-xs">
                        <span className="num text-ink-2">{a.code}</span>{' '}
                        <span className="text-ink">{a.name}</span>
                      </td>
                      <td className="td text-right">
                        <Money paisa={a.balance_paisa} variance />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          ) : null}

          <Panel title="Chart of accounts" bodyClassName="overflow-auto max-h-[280px]">
            <div className="divide-y divide-line/70">
              {journal.data.chart_of_accounts.map((a) => (
                <div key={a.code} className="px-3 py-1.5">
                  <div className="flex items-baseline justify-between">
                    <span className="text-xs text-ink">
                      <span className="num text-ink-2">{a.code}</span> {a.name}
                    </span>
                    <span className="chip border-line-strong bg-raised text-ink-3">
                      {a.account_type.toLowerCase()}
                    </span>
                  </div>
                  <p className="mt-0.5 text-2xs text-ink-3">{a.description}</p>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}

function Cell({
  label,
  value,
  tone = 'text-ink',
}: {
  label: string
  value: string
  tone?: string
}) {
  return (
    <div className="px-4 py-3">
      <div className="label flex h-7 items-start">{label}</div>
      <div className={`num text-xl font-semibold ${tone}`}>{value}</div>
    </div>
  )
}
