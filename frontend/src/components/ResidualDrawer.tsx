/**
 * Residual AI Evidence Drawer.
 *
 * Shows the full evidence package, deterministic confidence breakdown,
 * double-entry verification gate status, and human review decision buttons.
 */

import { useEffect, useState } from 'react'

import { Loading } from '@/components/primitives'
import { api } from '@/lib/api'
import { formatINR, formatPercent } from '@/lib/format'
import type { ArbitrationItem } from '@/types'

export function ResidualDrawer({
  residualId,
  onClose,
  onUpdated,
}: {
  residualId: string | null
  onClose: () => void
  onUpdated?: () => void
}) {
  const [item, setItem] = useState<ArbitrationItem | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionInProgress, setActionInProgress] = useState(false)

  useEffect(() => {
    if (!residualId) {
      setItem(null)
      return
    }
    setLoading(true)
    setError(null)
    api
      .arbitrationDetail(residualId)
      .then((data) => setItem(data))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load details'))
      .finally(() => setLoading(false))
  }, [residualId])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!residualId) return null

  const handleAction = async (action: 'approve' | 'reject' | 'unresolve') => {
    setActionInProgress(true)
    try {
      if (action === 'approve') {
        await api.approveArbitration(residualId)
      } else if (action === 'reject') {
        await api.rejectArbitration(residualId)
      } else {
        await api.unresolveArbitration(residualId)
      }
      const updated = await api.arbitrationDetail(residualId)
      setItem(updated)
      if (onUpdated) onUpdated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setActionInProgress(false)
    }
  }

  const meta = item?.model_metadata
  const breakdown = meta?.evidence_breakdown

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        aria-label="Close detail"
        className="flex-1 bg-black/50"
        onClick={onClose}
      />
      <aside className="flex h-full w-full max-w-[760px] flex-col border-l border-line-strong bg-panel shadow-2xl">
        {/* header */}
        <header className="shrink-0 border-b border-line px-5 py-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="num text-lg font-semibold text-accent">
                  {residualId}
                </span>
                {item ? (
                  <span
                    className={`chip ${
                      item.decision === 'RESOLVE'
                        ? 'border-matched/30 bg-matched/10 text-matched'
                        : item.decision === 'PROBABLE'
                        ? 'border-review/30 bg-review/10 text-review'
                        : 'border-exception/30 bg-exception/10 text-exception'
                    }`}
                  >
                    {item.decision}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 text-xs text-ink-3">
                Arbitrator: <span className="num font-medium text-ink-2">{item?.arbitrator ?? '—'}</span>
              </div>
            </div>
            <button className="btn shrink-0" onClick={onClose}>
              Close <span className="ml-1 text-ink-3">esc</span>
            </button>
          </div>
        </header>

        {loading ? (
          <div className="p-8">
            <Loading label="Loading residual arbitration detail" />
          </div>
        ) : error ? (
          <div className="p-5 text-sm text-exception">{error}</div>
        ) : item ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 space-y-5">
            {/* Status & Exception Banner */}
            <div
              className={`rounded border px-4 py-3 text-xs leading-relaxed ${
                meta?.auto_resolved
                  ? 'border-matched/40 bg-matched/[0.08] text-matched'
                  : item.requires_human_review
                  ? 'border-review/40 bg-review/[0.08] text-review'
                  : 'border-exception/40 bg-exception/[0.08] text-exception'
              }`}
            >
              <div className="font-semibold uppercase tracking-wider text-2xs mb-1">
                {meta?.auto_resolved
                  ? 'Auto-Resolved'
                  : item.requires_human_review
                  ? 'Human Review Required'
                  : 'Unresolved / High Uncertainty'}
              </div>
              <div>
                {meta?.auto_resolved
                  ? 'Final confidence exceeds auto-resolve threshold (>= 0.95). Verified and eligible for automated journal posting.'
                  : item.requires_human_review
                  ? 'Final confidence lies in human review band (0.70 - 0.95). Requires operator confirmation.'
                  : 'Confidence is below 0.70 or candidates are ambiguous. Left for manual exception resolution.'}
              </div>
            </div>

            {/* Verification Gate */}
            <div className="rounded border border-line bg-canvas p-3.5 space-y-2">
              <div className="flex items-center justify-between">
                <span className="label font-semibold">Double-Entry Verification Gate</span>
                <span
                  className={`chip ${
                    item.verification_accepted
                      ? 'border-matched/30 bg-matched/10 text-matched'
                      : 'border-exception/30 bg-exception/10 text-exception'
                  }`}
                >
                  {item.verification_accepted ? 'PASSED' : 'REJECTED BY GATE'}
                </span>
              </div>
              {!item.verification_accepted && item.verification_reasons.length > 0 ? (
                <div className="text-xs text-exception">
                  {item.verification_reasons.map((r, i) => (
                    <div key={i}>• {r}</div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-ink-3">
                  Journal batch verified: debit and credit balances match exactly. Money derived strictly from deterministic retrieval.
                </div>
              )}
            </div>

            {/* Evidence & Confidence Breakdown */}
            <div className="rounded border border-line bg-canvas p-3.5 space-y-3">
              <div className="label font-semibold">Confidence Breakdown</div>

              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded border border-line p-2 bg-panel">
                  <div className="text-2xs text-ink-3">Model Score</div>
                  <div className="num font-semibold text-accent mt-0.5">
                    {meta?.llm_confidence !== undefined
                      ? Number(meta.llm_confidence).toFixed(2)
                      : item.confidence.toFixed(2)}
                  </div>
                </div>
                <div className="rounded border border-line p-2 bg-panel">
                  <div className="text-2xs text-ink-3">Evidence Score</div>
                  <div className="num font-semibold text-accent mt-0.5">
                    {meta?.evidence_confidence !== undefined
                      ? Number(meta.evidence_confidence).toFixed(2)
                      : '—'}
                  </div>
                </div>
                <div className="rounded border border-line p-2 bg-panel">
                  <div className="text-2xs text-ink-3">Final Confidence</div>
                  <div className="num font-semibold text-matched mt-0.5">
                    {item.confidence.toFixed(2)}
                  </div>
                </div>
              </div>

              <div className="text-2xs text-ink-3 text-center italic">
                Formula: Final Confidence = 0.80 × Evidence Score + 0.20 × Model Confidence (capped at 0.90)
              </div>

              {breakdown ? (
                <div className="space-y-1.5 border-t border-line pt-2">
                  <div className="text-2xs uppercase tracking-wider text-ink-3 font-semibold">
                    Evidence Components
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="flex justify-between border-b border-line/50 pb-1">
                      <span className="text-ink-3">Identifier Similarity:</span>
                      <span className="num font-medium">{formatPercent(breakdown.identifier)}</span>
                    </div>
                    <div className="flex justify-between border-b border-line/50 pb-1">
                      <span className="text-ink-3">Amount Proximity:</span>
                      <span className="num font-medium">{formatPercent(breakdown.amount)}</span>
                    </div>
                    <div className="flex justify-between border-b border-line/50 pb-1">
                      <span className="text-ink-3">Date Proximity:</span>
                      <span className="num font-medium">{formatPercent(breakdown.date)}</span>
                    </div>
                    <div className="flex justify-between border-b border-line/50 pb-1">
                      <span className="text-ink-3">Counterparty Match:</span>
                      <span className="num font-medium">{formatPercent(breakdown.counterparty)}</span>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>

            {/* Reason & Explanation */}
            <div className="rounded border border-line bg-canvas p-3.5 space-y-1.5">
              <div className="label font-semibold">Arbitrator Reason & Analysis</div>
              <p className="text-xs leading-relaxed text-ink-2 whitespace-pre-wrap">
                {item.reason}
              </p>
            </div>

            {/* Candidates */}
            {item.candidates.length > 0 ? (
              <div className="rounded border border-line bg-canvas p-3.5 space-y-2">
                <div className="label font-semibold">
                  Candidates Found ({item.candidates.length})
                </div>
                <div className="space-y-2">
                  {item.candidates.map((c) => (
                    <div
                      key={c.candidate_id}
                      className="rounded border border-line bg-panel p-2 text-xs space-y-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="num font-semibold text-accent">
                          {c.candidate_id} ({c.kind})
                        </span>
                        <span className="num font-medium text-ink">
                          {formatINR(c.amount_paisa)}
                        </span>
                      </div>
                      {c.counterparty ? (
                        <div className="text-2xs text-ink-3">
                          Counterparty: {c.counterparty}
                        </div>
                      ) : null}
                      <div className="flex flex-wrap gap-1 text-2xs">
                        {c.amount_matches_exactly ? (
                          <span className="chip border-matched/30 bg-matched/10 text-matched">
                            exact amount
                          </span>
                        ) : (
                          <span className="chip border-line-strong bg-raised text-ink-3">
                            delta: {formatINR(Math.abs(c.amount_delta_paisa))}
                          </span>
                        )}
                        {c.basis.map((b, i) => (
                          <span key={i} className="chip border-line-strong bg-canvas text-ink-3">
                            {b}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {/* Human Review Decision Buttons */}
            <div className="rounded border border-line-strong bg-panel p-4 space-y-3">
              <div className="label font-semibold text-sm">Human Review Actions</div>
              <div className="flex gap-2">
                <button
                  className="btn-accent flex-1 justify-center bg-matched hover:bg-matched/90 text-white"
                  onClick={() => handleAction('approve')}
                  disabled={actionInProgress}
                >
                  Approve & Post Journal
                </button>
                <button
                  className="btn flex-1 justify-center border-exception/40 text-exception hover:bg-exception/10"
                  onClick={() => handleAction('reject')}
                  disabled={actionInProgress}
                >
                  Reject Proposal
                </button>
                <button
                  className="btn flex-1 justify-center border-line-strong text-ink-2 hover:bg-hover"
                  onClick={() => handleAction('unresolve')}
                  disabled={actionInProgress}
                >
                  Mark Unresolved
                </button>
              </div>
            </div>
          </div>
        ) : null}
      </aside>
    </div>
  )
}
