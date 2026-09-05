/**
 * Copilot: grounded Q&A plus the arbitration console.
 *
 * Every answer is retrieved from what the run proved, and each one carries the
 * facts it was built from. The provenance line under each answer is not
 * decoration: it is how an operator confirms the copilot is reading the same
 * numbers as the dashboard.
 *
 * The right pane runs arbitration and shows exactly what a model would be
 * handed - residual cases and nothing else.
 */

import { useEffect, useRef, useState } from 'react'

import { RecordDrawer } from '@/components/RecordDrawer'
import { ResidualDrawer } from '@/components/ResidualDrawer'
import { EmptyState, ErrorState, Loading, Panel } from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { useRunContext } from '@/hooks/useRunContext'
import { api } from '@/lib/api'
import { formatINR, formatNumber, formatPercent } from '@/lib/format'
import type { ArbitrationRunResult, CopilotAnswer, EvaluationMetrics } from '@/types'

const SUGGESTIONS = [
  'Will we meet payroll next Friday?',
  'Why did settlement dip Tuesday?',
  'What cash is at risk?',
  'Show unresolved cash exposure',
  'Which settlement delays matter most?',
  'What changed since the last run?',
  'What did the arbitrator propose?',
  'What journal entries are pending?',
]

const DECISION_TONE: Record<string, string> = {
  RESOLVE: 'border-matched/30 bg-matched/10 text-matched',
  PROBABLE: 'border-review/30 bg-review/10 text-review',
  UNRESOLVED: 'border-exception/30 bg-exception/10 text-exception',
}

interface Turn {
  question: string
  answer: CopilotAnswer | null
  error?: string
}

export function Copilot() {
  const { activeRunId, health } = useRunContext()
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [thinking, setThinking] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedResidual, setSelectedResidual] = useState<string | null>(null)
  const [arbitratorType, setArbitratorType] = useState<string>('mock')
  const [arbitrating, setArbitrating] = useState(false)
  const [evaluating, setEvaluating] = useState(false)
  const [evalMetrics, setEvalMetrics] = useState<EvaluationMetrics | null>(null)
  const [lastRun, setLastRun] = useState<ArbitrationRunResult | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const results = useApi(
    () => api.arbitrationResults({ run_id: activeRunId ?? undefined, limit: 100 }),
    [activeRunId, lastRun],
    { enabled: Boolean(activeRunId) },
  )

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' })
  }, [turns, thinking])

  if (!activeRunId) {
    return <EmptyState title="No run selected" detail="Start a reconciliation run first." />
  }

  const ask = async (question: string) => {
    const trimmed = question.trim()
    if (!trimmed || thinking) return
    setInput('')
    setThinking(true)
    setTurns((t) => [...t, { question: trimmed, answer: null }])
    try {
      const answer = await api.askCopilot(trimmed, activeRunId)
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, answer } : turn)),
      )
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Request failed'
      setTurns((t) =>
        t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: message } : turn)),
      )
    } finally {
      setThinking(false)
    }
  }

  const runArbitration = async () => {
    setArbitrating(true)
    try {
      const result = await api.runArbitration({
        run_id: activeRunId,
        arbitrator: arbitratorType,
        propose_rules: true,
      })
      setLastRun(result)
      results.refetch()
    } finally {
      setArbitrating(false)
    }
  }

  const runEvaluation = async () => {
    setEvaluating(true)
    try {
      const metrics = await api.evaluateArbitration(activeRunId)
      setEvalMetrics(metrics)
    } catch (err) {
      console.error('Evaluation failed:', err)
    } finally {
      setEvaluating(false)
    }
  }

  const summary = results.data?.summary

  return (
    <div className="flex h-full gap-3 p-3">
      {/* ---- conversation ---- */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <Panel
          className="min-h-0 flex-1"
          bodyClassName="flex flex-col min-h-0"
          title="Finance copilot"
          note="Answers are retrieved from what this run proved. No figure is generated."
        >
          <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
            {turns.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
                <p className="text-md text-ink-2">
                  Ask about this reconciliation run.
                </p>
                <p className="max-w-md text-xs leading-relaxed text-ink-3">
                  Every answer traces back to source records, an accounting
                  derivation and audit events. If the question cannot be mapped
                  onto a stored fact, the copilot says so rather than guessing.
                </p>
                <div className="mt-2 flex max-w-lg flex-wrap justify-center gap-1.5">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => ask(s)}
                      className="chip border-line-strong bg-raised text-ink-2 hover:border-accent/50 hover:text-accent"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                {turns.map((turn, index) => (
                  <div key={index} className="space-y-2">
                    <div className="flex justify-end">
                      <div className="max-w-[80%] rounded border border-line-strong bg-raised px-3 py-1.5 text-sm">
                        {turn.question}
                      </div>
                    </div>

                    {turn.error ? (
                      <div className="rounded border border-exception/40 bg-exception/[0.07] px-3 py-2 text-sm text-exception">
                        {turn.error}
                      </div>
                    ) : turn.answer ? (
                      <AnswerCard
                        answer={turn.answer}
                        onAsk={ask}
                        onOpen={setSelected}
                      />
                    ) : (
                      <Loading label="Retrieving" />
                    )}
                  </div>
                ))}
                <div ref={bottom} />
              </div>
            )}
          </div>

          <form
            className="flex shrink-0 gap-2 border-t border-line px-3 py-2"
            onSubmit={(e) => {
              e.preventDefault()
              ask(input)
            }}
          >
            <input
              className="input flex-1"
              placeholder="Ask about matches, exceptions, unexplained value, journals…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={thinking}
            />
            <button className="btn-accent" type="submit" disabled={thinking || !input.trim()}>
              {thinking ? 'Retrieving…' : 'Ask'}
            </button>
          </form>
        </Panel>
      </div>

      {/* ---- arbitration console ---- */}
      <div className="flex w-[450px] shrink-0 flex-col gap-3">
        <Panel title="Residual AI Arbitrator">
          <div className="px-4 py-3 space-y-3">
            <div className="flex items-baseline justify-between">
              <div>
                <div className="label">Residuals examined</div>
                <div className="num mt-1 text-2xl font-semibold text-review">
                  {formatNumber(summary?.total ?? 0)}
                </div>
              </div>
              <div className="text-right">
                <div className="label">Rejected by verification</div>
                <div
                  className={`num mt-1 text-2xl font-semibold ${
                    (summary?.rejected_by_verification ?? 0) > 0
                      ? 'text-exception'
                      : 'text-matched'
                  }`}
                >
                  {formatNumber(summary?.rejected_by_verification ?? 0)}
                </div>
              </div>
            </div>

            {summary ? (
              <div className="flex flex-wrap gap-1.5 border-t border-line pt-2">
                {Object.entries(summary.decisions).map(([decision, count]) => (
                  <span
                    key={decision}
                    className={`chip ${DECISION_TONE[decision] ?? 'border-line-strong bg-raised text-ink-2'}`}
                  >
                    {decision.toLowerCase()} {count}
                  </span>
                ))}
              </div>
            ) : null}

            {/* AI Cost & Utilization Metrics */}
            {summary && (summary.total_tokens !== undefined || summary.auto_resolved_count !== undefined) ? (
              <div className="rounded border border-line bg-canvas p-2.5 space-y-1 text-xs">
                <div className="text-2xs uppercase tracking-wider text-ink-3 font-semibold">
                  AI Cost & Utilization Summary
                </div>
                <div className="grid grid-cols-2 gap-2 text-ink-2">
                  <div>
                    Tokens: <span className="num font-medium">{formatNumber(summary.total_tokens ?? 0)}</span>
                  </div>
                  <div>
                    Est. Cost: <span className="num font-medium">${(summary.estimated_cost_usd ?? 0).toFixed(4)}</span>
                  </div>
                  <div>
                    Auto-resolved: <span className="num font-medium text-matched">{summary.auto_resolved_count ?? 0}</span>
                  </div>
                  <div>
                    Human review: <span className="num font-medium text-review">{summary.human_review_count ?? 0}</span>
                  </div>
                </div>
              </div>
            ) : null}

            {/* Arbitrator Selector */}
            <div className="flex items-center gap-2">
              <label className="label text-xs" htmlFor="arbitrator-select">
                Provider:
              </label>
              <select
                id="arbitrator-select"
                className="input num text-xs flex-1"
                value={arbitratorType}
                onChange={(e) => setArbitratorType(e.target.value)}
              >
                <option value="mock">Mock Arbitrator (Synthetic Anomalies)</option>
                <option value="llm">LLM Arbitrator ({health?.ai_provider ?? 'llm'})</option>
                <option value="deterministic">Deterministic Engine Baseline</option>
              </select>
            </div>

            <div className="flex gap-2">
              <button
                className="btn-accent flex-1 justify-center"
                onClick={runArbitration}
                disabled={arbitrating}
              >
                {arbitrating ? 'Arbitrating…' : 'Run Residual Arbitration'}
              </button>
              <button
                className="btn justify-center border-accent/40 text-accent hover:bg-accent/10"
                onClick={runEvaluation}
                disabled={evaluating}
                title="Run Ground-Truth Evaluation against synthetic anomaly labels"
              >
                {evaluating ? 'Evaluating…' : 'Evaluate Harness'}
              </button>
            </div>

            {/* Evaluation Metrics Card */}
            {evalMetrics ? (
              <div className="rounded border border-accent/30 bg-accent/[0.04] p-3 text-xs space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-accent uppercase tracking-wider text-2xs">
                    Ground-Truth Evaluation Results
                  </span>
                  <span className="chip border-accent/30 bg-accent/10 text-accent">
                    F1: {evalMetrics.f1_score.toFixed(3)}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center text-ink-2">
                  <div className="rounded border border-line bg-panel p-1.5">
                    <div className="text-2xs text-ink-3">Precision</div>
                    <div className="num font-semibold text-matched">{formatPercent(evalMetrics.precision)}</div>
                  </div>
                  <div className="rounded border border-line bg-panel p-1.5">
                    <div className="text-2xs text-ink-3">Recall</div>
                    <div className="num font-semibold text-review">{formatPercent(evalMetrics.recall)}</div>
                  </div>
                  <div className="rounded border border-line bg-panel p-1.5">
                    <div className="text-2xs text-ink-3">Accuracy</div>
                    <div className="num font-semibold text-ink">{formatPercent(evalMetrics.accuracy)}</div>
                  </div>
                </div>
                <div className="flex justify-between text-2xs text-ink-3 border-t border-line/60 pt-1.5">
                  <span>Overrides Prevented: <strong className="num text-matched">{evalMetrics.overrides_prevented}</strong></span>
                  <span>Coverage: <strong className="num">{formatPercent(evalMetrics.coverage)}</strong></span>
                </div>
              </div>
            ) : null}

            {lastRun ? (
              <div className="rounded border border-line bg-canvas px-3 py-2 text-xs">
                <div className="text-ink-2">
                  {lastRun.residuals_examined} examined ·{' '}
                  {lastRun.journal_entries_proposed} journal entries proposed
                </div>
                {lastRun.rule_proposals.length > 0 ? (
                  <div className="mt-1.5 border-t border-line pt-1.5">
                    <span className="chip border-accent/40 bg-accent/10 text-accent">
                      {lastRun.rule_proposals.length} rule proposed
                    </span>
                    {lastRun.rule_proposals.map((p) => (
                      <div key={p.rule_id} className="mt-1 text-ink-3">
                        <span className="num text-accent">{p.rule_id}</span> induced
                        from {p.support} pairings — review it on the Rules page.
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </Panel>

        <Panel
          className="min-h-0 flex-1"
          bodyClassName="overflow-auto"
          title="Proposals Queue"
          note="Click any item for full Evidence Drawer & Human Actions."
        >
          {results.loading && !results.data ? (
            <Loading />
          ) : results.error ? (
            <ErrorState message={results.error} />
          ) : (results.data?.items.length ?? 0) === 0 ? (
            <EmptyState
              title="No arbitration yet"
              detail="Run arbitration to produce proposals from this run's residuals."
            />
          ) : (
            <div className="divide-y divide-line/70">
              {results.data!.items.map((item) => (
                <button
                  key={item.residual_id}
                  onClick={() => setSelectedResidual(item.residual_id)}
                  className="row flex w-full flex-col gap-1 px-3 py-2.5 text-left hover:bg-hover transition-colors"
                >
                  <div className="flex w-full items-center gap-2">
                    <span className="num text-sm text-accent">{item.residual_id}</span>
                    <span className={`chip ${DECISION_TONE[item.decision] ?? ''}`}>
                      {item.decision.toLowerCase()}
                    </span>
                    {item.requires_human_review ? (
                      <span className="chip border-review/40 bg-review/10 text-review">
                        human review
                      </span>
                    ) : null}
                    <span className="num ml-auto text-xs text-ink-2">
                      {formatINR(item.amount_paisa)}
                    </span>
                  </div>
                  {item.proposed_action ? (
                    <div className="text-2xs text-ink-2">
                      {item.proposed_action.toLowerCase().replace(/_/g, ' ')} ·
                      confidence {item.confidence.toFixed(2)}
                    </div>
                  ) : null}
                  <p className="text-2xs leading-relaxed text-ink-3">
                    {item.reason.length > 150
                      ? `${item.reason.slice(0, 150)}…`
                      : item.reason}
                  </p>
                  {!item.verification_accepted ? (
                    <div className="text-2xs text-exception font-medium">
                      rejected by gate: {item.verification_reasons[0]}
                    </div>
                  ) : null}
                </button>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <RecordDrawer
        reconciliationId={selected}
        runId={activeRunId}
        onClose={() => setSelected(null)}
      />

      <ResidualDrawer
        residualId={selectedResidual}
        onClose={() => setSelectedResidual(null)}
        onUpdated={() => results.refetch()}
      />
    </div>
  )
}

function AnswerCard({
  answer,
  onAsk,
  onOpen,
}: {
  answer: CopilotAnswer
  onAsk: (q: string) => void
  onOpen: (id: string) => void
}) {
  return (
    <div className="rounded border border-line bg-canvas px-3.5 py-3 space-y-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="chip border-accent/30 bg-accent/10 text-accent font-medium">
          {answer.intent.toLowerCase().replace(/_/g, ' ')}
        </span>
        {answer.grounded ? (
          <span className="chip border-matched/30 bg-matched/10 text-matched">
            grounded
          </span>
        ) : null}
        <span className="chip border-line-strong bg-raised text-ink-3">
          confidence: {answer.confidence ?? 1.0} ({answer.confidence_method ?? 'DETERMINISTIC'})
        </span>
      </div>

      <div>
        <div className="text-2xs font-semibold uppercase tracking-wider text-accent">Answer</div>
        <p className="text-sm font-medium leading-relaxed text-ink mt-0.5">{answer.answer}</p>
      </div>

      {answer.why ? (
        <div className="rounded border border-line/60 bg-panel p-2 text-xs">
          <div className="text-2xs font-semibold uppercase tracking-wider text-ink-3">Why</div>
          <p className="text-ink-2 leading-relaxed mt-0.5">{answer.why}</p>
        </div>
      ) : null}

      {answer.financial_impact ? (
        <div className="rounded border border-matched/20 bg-matched/[0.04] p-2 text-xs">
          <div className="text-2xs font-semibold uppercase tracking-wider text-matched">Financial Impact</div>
          <p className="text-ink-2 font-medium mt-0.5">{answer.financial_impact}</p>
        </div>
      ) : null}

      {answer.risk ? (
        <div className="rounded border border-review/30 bg-review/[0.05] p-2 text-xs">
          <div className="text-2xs font-semibold uppercase tracking-wider text-review">Risk Assessment</div>
          <p className="text-ink-2 font-medium mt-0.5">{answer.risk}</p>
        </div>
      ) : null}

      {answer.recommended_action ? (
        <div className="rounded border border-accent/30 bg-accent/[0.05] p-2 text-xs">
          <div className="text-2xs font-semibold uppercase tracking-wider text-accent">Recommended Action</div>
          <p className="text-accent font-medium mt-0.5">{answer.recommended_action}</p>
        </div>
      ) : null}

      {answer.facts.length > 0 ? (
        <div>
          <div className="text-2xs font-semibold uppercase tracking-wider text-ink-3 mb-1">Verified Facts</div>
          <div className="divide-y divide-line/70 rounded border border-line">
            {answer.facts.map((fact, index) => (
              <div key={index} className="flex items-baseline gap-3 px-2.5 py-1 text-xs">
                <span className="w-44 shrink-0 text-ink-3">{fact.label}</span>
                <span className="num min-w-0 flex-1 break-all text-ink-2 font-medium">
                  {fact.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {(answer.records.length > 0 || (answer.citations && answer.citations.length > 0)) ? (
        <div>
          <div className="text-2xs font-semibold uppercase tracking-wider text-ink-3 mb-1">Evidence & Citations</div>
          <div className="flex flex-wrap gap-1">
            {(answer.citations && answer.citations.length > 0
              ? answer.citations.map((c) => c.record_id)
              : answer.records
            )
              .slice(0, 10)
              .map((id) => (
                <button
                  key={id}
                  onClick={() => (id.startsWith('REC-') ? onOpen(id) : undefined)}
                  className={`chip num border-line-strong bg-raised text-accent ${
                    id.startsWith('REC-') ? 'hover:border-accent hover:bg-accent/10' : ''
                  }`}
                >
                  [{id}]
                </button>
              ))}
          </div>
        </div>
      ) : null}

      {answer.followups.filter(Boolean).length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5 border-t border-line pt-2">
          {answer.followups.filter(Boolean).map((f) => (
            <button key={f} onClick={() => onAsk(f)} className="text-2xs text-accent hover:underline">
              {f} →
            </button>
          ))}
        </div>
      ) : null}

      <div className="mt-2 text-2xs text-ink-3 flex items-center justify-between border-t border-line/50 pt-1.5">
        <span>produced by <span className="num">{answer.generated_by}</span></span>
        <span>governed by <span className="num font-medium text-matched">deterministic accounting</span></span>
      </div>
    </div>
  )
}
