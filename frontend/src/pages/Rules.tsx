/**
 * Rules: the self-healing workflow, end to end.
 *
 * A proposed rule cannot be promoted straight from this screen. The Promote
 * button is disabled until a replay has produced evidence, and it demands a
 * named actor, because promotion is the one action here that changes what the
 * engine matches on every future run.
 *
 * Validation results are shown as measured deltas rather than a verdict badge
 * alone: the number of records that moved, and critically whether anything
 * regressed, is what an approver actually needs to see.
 */

import { useState } from 'react'

import {
  ErrorState,
  Loading,
  Money,
  Panel,
} from '@/components/primitives'
import { useApi } from '@/hooks/useApi'
import { api } from '@/lib/api'
import { formatDateTime, formatNumber, formatPercent } from '@/lib/format'
import type { Rule, RuleDemoResponse, RuleValidation } from '@/types'

const STATUS_TONE: Record<string, string> = {
  ACTIVE: 'border-matched/30 bg-matched/10 text-matched',
  APPROVED: 'border-partial/30 bg-partial/10 text-partial',
  PROPOSED: 'border-review/30 bg-review/10 text-review',
  VALIDATING: 'border-review/30 bg-review/10 text-review',
  REJECTED: 'border-exception/30 bg-exception/10 text-exception',
  RETIRED: 'border-line-strong bg-raised text-ink-3',
}

const TYPE_TONE: Record<string, string> = {
  ACCOUNTING: 'border-matched/30 bg-matched/10 text-matched',
  MATCHING: 'border-partial/30 bg-partial/10 text-partial',
  NORMALIZATION: 'border-duplicate/30 bg-duplicate/10 text-duplicate',
  CLASSIFICATION: 'border-review/30 bg-review/10 text-review',
  REFERENCE_EXTRACTION: 'border-accent/40 bg-accent/10 text-accent',
  AMOUNT_TOLERANCE: 'border-matched/40 bg-matched/10 text-matched',
  DATE_TOLERANCE: 'border-review/40 bg-review/10 text-review',
}

const VERDICT_TONE: Record<string, string> = {
  IMPROVES: 'text-matched',
  NEUTRAL: 'text-ink-2',
  REGRESSES: 'text-exception',
  INVALID: 'text-exception',
}

export function Rules() {
  const { data, error, loading, refetch } = useApi(() => api.ruleCatalogue(), [])
  const [actor, setActor] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [typeFilter, setTypeFilter] = useState('')
  const [demoRunning, setDemoRunning] = useState(false)
  const [demoResult, setDemoResult] = useState<RuleDemoResponse | null>(null)

  if (loading && !data) return <Loading label="Loading rule catalogue" />
  if (error) return <ErrorState message={error} />
  if (!data) return null

  const act = async (fn: () => Promise<unknown>, label: string) => {
    setBusy(label)
    setMessage(null)
    try {
      await fn()
      refetch()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(null)
    }
  }

  const runDemo = async () => {
    setDemoRunning(true)
    setMessage(null)
    try {
      const res = await api.runRuleDemo()
      setDemoResult(res)
      refetch()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Demo execution failed')
    } finally {
      setDemoRunning(false)
    }
  }

  const dynamic = data.rules.filter((r: Rule) => r.is_dynamic)
  const builtIn = data.rules.filter((r: Rule) => !r.is_dynamic)
  const types = Array.from(new Set(builtIn.map((r: Rule) => r.rule_type))).sort()
  const shown = typeFilter
    ? builtIn.filter((r: Rule) => r.rule_type === typeFilter)
    : builtIn
  const latestValidation = (ruleId: string): RuleValidation | undefined =>
    data.validations.find((v: RuleValidation) => v.rule_id === ruleId)

  return (
    <div className="flex flex-col gap-3 p-3">
      {/* ---- summary strip ---- */}
      <div className="panel grid grid-cols-2 divide-x divide-line md:grid-cols-5 items-center">
        <SummaryCell label="Rules in catalogue" value={formatNumber(data.total)} />
        <SummaryCell
          label="Active"
          value={formatNumber(data.by_status.ACTIVE ?? 0)}
          tone="text-matched"
        />
        <SummaryCell
          label="Awaiting promotion"
          value={formatNumber(data.by_status.APPROVED ?? 0)}
          tone="text-partial"
        />
        <SummaryCell
          label="Proposed by arbitration"
          value={formatNumber(data.by_status.PROPOSED ?? 0)}
          tone="text-review"
        />
        <div className="px-4 py-3 flex flex-col justify-center items-center">
          <button
            className="btn-accent w-full justify-center text-xs py-2 bg-accent hover:bg-accent/90"
            onClick={runDemo}
            disabled={demoRunning}
            title="Run end-to-end self-healing demo scenario in under 90s"
          >
            {demoRunning ? 'Running 90s Demo…' : '⚡ Run 90s Demo Scenario'}
          </button>
        </div>
      </div>

      {/* ---- Demo Scenario Result Card ---- */}
      {demoResult ? (
        <div className="panel border-accent/40 bg-accent/[0.04] px-5 py-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="chip border-accent/40 bg-accent/10 text-accent font-semibold">
                DEMO SCENARIO COMPLETE
              </span>
              <span className="text-sm font-semibold text-ink">
                {demoResult.message}
              </span>
            </div>
            <button
              className="text-2xs text-ink-3 hover:text-ink"
              onClick={() => setDemoResult(null)}
            >
              Dismiss
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div className="rounded border border-line bg-canvas p-2.5">
              <div className="text-2xs text-ink-3">Deterministic Coverage</div>
              <div className="num font-semibold text-matched mt-0.5">
                {demoResult.deterministic_coverage_before_pct.toFixed(1)}% →{' '}
                {demoResult.deterministic_coverage_after_pct.toFixed(1)}%
              </div>
            </div>
            <div className="rounded border border-line bg-canvas p-2.5">
              <div className="text-2xs text-ink-3">AI Residual Workload</div>
              <div className="num font-semibold text-review mt-0.5">
                {demoResult.baseline_residuals} → {demoResult.after_residuals} (-{demoResult.residual_reduction})
              </div>
            </div>
            <div className="rounded border border-line bg-canvas p-2.5">
              <div className="text-2xs text-ink-3">AI Dependency Reduction</div>
              <div className="num font-semibold text-matched text-base mt-0.5">
                {demoResult.ai_dependency_reduction_pct.toFixed(1)}%
              </div>
            </div>
            <div className="rounded border border-line bg-canvas p-2.5">
              <div className="text-2xs text-ink-3">Est. Cost Avoided</div>
              <div className="num font-semibold text-ink mt-0.5">
                ${demoResult.estimated_ai_cost_avoided_usd.toFixed(4)} USD
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {message ? (
        <div className="panel border-exception/40 bg-exception/[0.07] px-4 py-2 text-sm text-exception">
          {message}
        </div>
      ) : null}

      {/* ---- self-healing workflow ---- */}
      <Panel
        title={`Self-healing rules · ${dynamic.length}`}
        actions={
          <div className="flex items-center gap-2">
            <label className="label" htmlFor="actor">
              Acting as
            </label>
            <input
              id="actor"
              className="input w-52"
              placeholder="your.name@company.com"
              value={actor}
              onChange={(e) => setActor(e.target.value)}
            />
          </div>
        }
        note="A rule reaches ACTIVE only after a replay proves it helps AND a named person promotes it. Both gates are enforced server-side."
      >
        {dynamic.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-ink-3">
            No rules have been proposed yet. Run arbitration on a run with
            unresolved reference formats or gateway rounding, and the arbitrator will induce one from
            the evidence.
          </div>
        ) : (
          <div className="divide-y divide-line">
            {dynamic.map((rule) => {
              const validation = latestValidation(rule.rule_id)
              const canPromote = rule.status === 'APPROVED' && actor.trim().length > 0
              return (
                <article key={rule.rule_id} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="num text-md font-semibold text-accent">
                          {rule.rule_id}
                        </span>
                        <span className="chip border-line-strong bg-canvas text-ink-3 num">
                          v{rule.version ?? 1}
                        </span>
                        <span className={`chip ${STATUS_TONE[rule.status] ?? ''}`}>
                          {rule.status.toLowerCase()}
                        </span>
                        <span
                          className={`chip ${TYPE_TONE[rule.rule_type] ?? 'border-line-strong bg-raised text-ink-2'}`}
                        >
                          {rule.rule_type.toLowerCase().replace(/_/g, ' ')}
                        </span>
                        {rule.proposed_from_run ? (
                          <span className="num text-2xs text-ink-3">
                            from {rule.proposed_from_run}
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-1 text-sm text-ink font-medium">{rule.name}</div>
                      <p className="mt-1 max-w-3xl text-xs leading-relaxed text-ink-2">
                        {rule.description}
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {rule.parameters.pattern ? (
                          <code className="num rounded border border-line bg-canvas px-2 py-1 text-2xs text-ink">
                            {String(rule.parameters.pattern ?? '')}
                          </code>
                        ) : null}
                        {rule.parameters.marker ? (
                          <span className="chip border-line-strong bg-raised text-ink-3">
                            anchor {String(rule.parameters.marker ?? '')}
                          </span>
                        ) : null}
                        {rule.parameters.tolerance_paisa ? (
                          <span className="chip border-matched/30 bg-matched/10 text-matched num">
                            tolerance ±{String(rule.parameters.tolerance_paisa)} paisa
                          </span>
                        ) : null}
                        <span className="chip border-line-strong bg-raised text-ink-3 num">
                          {rule.supporting_residuals?.length ?? 0} supporting residuals
                        </span>
                        {rule.approved_by ? (
                          <span className="chip border-matched/30 bg-matched/10 text-matched">
                            approved by {rule.approved_by}
                          </span>
                        ) : null}
                      </div>
                    </div>

                    <div className="flex shrink-0 gap-1.5">
                      <button
                        className="btn"
                        disabled={busy !== null}
                        onClick={() =>
                          act(
                            () => api.validateRule(rule.rule_id),
                            `validate-${rule.rule_id}`,
                          )
                        }
                        title="Replay this rule over the dataset and measure the effect"
                      >
                        {busy === `validate-${rule.rule_id}` ? 'Replaying…' : 'Validate by replay'}
                      </button>
                      <button
                        className="btn-accent"
                        disabled={!canPromote || busy !== null}
                        title={
                          rule.status !== 'APPROVED'
                            ? 'A rule must pass a replay before it can be promoted'
                            : !actor.trim()
                              ? 'Promotion must be attributed: enter who is acting'
                              : 'Activate this rule for every future run'
                        }
                        onClick={() =>
                          act(
                            () => api.decideRule(rule.rule_id, 'promote', actor),
                            `promote-${rule.rule_id}`,
                          )
                        }
                      >
                        Promote
                      </button>
                      {rule.status === 'ACTIVE' ? (
                        <button
                          className="btn"
                          disabled={!actor.trim() || busy !== null}
                          onClick={() =>
                            act(
                              () => api.decideRule(rule.rule_id, 'retire', actor),
                              `retire-${rule.rule_id}`,
                            )
                          }
                        >
                          Retire
                        </button>
                      ) : (
                        <button
                          className="btn"
                          disabled={!actor.trim() || busy !== null}
                          onClick={() =>
                            act(
                              () => api.decideRule(rule.rule_id, 'reject', actor),
                              `reject-${rule.rule_id}`,
                            )
                          }
                        >
                          Reject
                        </button>
                      )}
                    </div>
                  </div>

                  {rule.decision_note ? (
                    <p className="mt-2 text-xs text-ink-3">{rule.decision_note}</p>
                  ) : null}

                  {validation ? (
                    <ValidationCard validation={validation} />
                  ) : (
                    <div className="mt-2 rounded border border-line bg-canvas px-3 py-2 text-xs text-ink-3">
                      Not yet replayed. Promotion is blocked until a replay
                      produces evidence.
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </Panel>

      {/* ---- lifecycle + built-ins ---- */}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-4">
        <Panel title="Promotion lifecycle" className="xl:col-span-1">
          <ol className="px-4 py-3">
            {data.lifecycle.map((stage: { status: string; note: string }, index: number) => (
              <li key={stage.status} className="relative pb-3 pl-5 last:pb-0">
                {index < data.lifecycle.length - 1 ? (
                  <span className="absolute left-[3px] top-3 h-full w-px bg-line" />
                ) : null}
                <span
                  className={`absolute left-0 top-1.5 h-1.5 w-1.5 rounded-full ${
                    (data.by_status[stage.status] ?? 0) > 0
                      ? 'bg-accent'
                      : 'bg-line-strong'
                  }`}
                />
                <div className="flex items-baseline justify-between">
                  <span className="label text-ink-2">{stage.status}</span>
                  <span className="num text-2xs text-ink-3">
                    {data.by_status[stage.status] ?? 0}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-ink-3">{stage.note}</p>
              </li>
            ))}
          </ol>
          <div className="border-t border-line px-4 py-3">
            <p className="text-xs leading-relaxed text-ink-2">{data.note}</p>
          </div>
        </Panel>

        <Panel
          className="xl:col-span-3"
          bodyClassName="overflow-auto max-h-[520px]"
          title={`Built-in deterministic rules · ${shown.length}`}
          actions={
            <select
              className="input"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">All types</option>
              {types.map((t: string) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          }
        >
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="th w-[120px]">Rule</th>
                <th className="th w-[180px]">Name</th>
                <th className="th w-[120px]">Type</th>
                <th className="th">Expression</th>
                <th className="th w-[80px]">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((rule: Rule) => (
                <tr key={rule.rule_id} className="hover:bg-hover">
                  <td className="td num text-accent">{rule.rule_id}</td>
                  <td className="td text-ink">{rule.name}</td>
                  <td className="td">
                    <span
                      className={`chip ${TYPE_TONE[rule.rule_type] ?? 'border-line-strong bg-raised text-ink-2'}`}
                    >
                      {rule.rule_type.toLowerCase()}
                    </span>
                  </td>
                  <td className="td num text-xs text-ink-2">{rule.expression}</td>
                  <td className="td">
                    <span className={`chip ${STATUS_TONE[rule.status] ?? ''}`}>
                      {rule.status.toLowerCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  )
}

function ValidationCard({ validation }: { validation: RuleValidation }) {
  const tone = VERDICT_TONE[validation.verdict] ?? 'text-ink-2'
  const detail = validation.detail || {}

  return (
    <div className="mt-2 rounded border border-line bg-canvas px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <span className="label">Replay evidence</span>
          <span className="num text-2xs text-ink-3">
            {validation.validation_id} · {validation.dataset_id} ·{' '}
            {formatDateTime(validation.created_at)}
          </span>
        </div>
        <span className={`text-md font-semibold ${tone}`}>{validation.verdict}</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 md:grid-cols-4">
        <Delta
          label="Deterministic matches"
          before={validation.baseline_matches}
          after={validation.candidate_matches}
          delta={validation.match_delta}
          goodWhenPositive
        />
        <Delta
          label="Residuals"
          before={validation.baseline_residuals}
          after={validation.candidate_residuals}
          delta={validation.residual_delta}
        />
        <div>
          <div className="label">Match rate</div>
          <div className="num mt-0.5 text-sm">
            {formatPercent(validation.baseline_match_rate)} →{' '}
            {formatPercent(validation.candidate_match_rate)}
            <span
              className={`ml-1.5 ${validation.match_rate_delta_pct >= 0 ? 'text-matched' : 'text-exception'}`}
            >
              {validation.match_rate_delta_pct >= 0 ? '+' : ''}
              {validation.match_rate_delta_pct.toFixed(2)}pp
            </span>
          </div>
        </div>
        <div>
          <div className="label">Regressions</div>
          <div
            className={`num mt-0.5 text-sm ${validation.regressions.length ? 'text-exception' : 'text-matched'}`}
          >
            {validation.regressions.length === 0
              ? 'none'
              : `${validation.regressions.length} record(s)`}
          </div>
        </div>
      </div>

      {detail.estimated_ai_calls_avoided !== undefined ? (
        <div className="mt-2 flex flex-wrap gap-4 border-t border-line pt-2 text-xs">
          <div>
            <span className="text-ink-3">AI Calls Avoided: </span>
            <span className="num font-semibold text-matched">
              {String(detail.estimated_ai_calls_avoided)}
            </span>
          </div>
          <div>
            <span className="text-ink-3">Est. AI Cost Avoided: </span>
            <span className="num font-semibold text-ink font-mono">
              ${Number(detail.estimated_cost_avoided_usd ?? 0).toFixed(4)} USD
            </span>
          </div>
          {typeof detail.precision === 'number' ? (
            <div>
              <span className="text-ink-3">Precision: </span>
              <span className="num font-semibold text-matched font-mono">
                {formatPercent(detail.precision as number)}
              </span>
            </div>
          ) : null}
        </div>
      ) : null}

      {typeof validation.detail.unexplained_delta_paisa === 'number' ? (
        <div className="mt-1 flex items-baseline gap-2 border-t border-line/50 pt-1 text-xs">
          <span className="text-ink-3">Unexplained value change:</span>
          <Money
            paisa={validation.detail.unexplained_delta_paisa as number}
            variance
          />
        </div>
      ) : null}

      {validation.regressions.length > 0 ? (
        <ul className="mt-2 space-y-0.5 border-t border-line pt-2">
          {validation.regressions.slice(0, 5).map((r) => (
            <li key={r} className="num text-2xs text-exception">
              {r}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function Delta({
  label,
  before,
  after,
  delta,
  goodWhenPositive = false,
}: {
  label: string
  before: number
  after: number
  delta: number
  goodWhenPositive?: boolean
}) {
  const good = goodWhenPositive ? delta > 0 : delta < 0
  const tone = delta === 0 ? 'text-ink-3' : good ? 'text-matched' : 'text-exception'
  return (
    <div>
      <div className="label">{label}</div>
      <div className="num mt-0.5 text-sm">
        {formatNumber(before)} → {formatNumber(after)}
        <span className={`ml-1.5 ${tone}`}>
          {delta > 0 ? '+' : ''}
          {delta}
        </span>
      </div>
    </div>
  )
}

function SummaryCell({
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
