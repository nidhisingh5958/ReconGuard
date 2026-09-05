/**
 * Type contracts for ReconGuard API.
 *
 * Every money figure is an integer number of paise.
 * Dates are ISO 8601 strings.
 */

export type ReconciliationStatus =
  | 'MATCHED'
  | 'PARTIAL_MATCH'
  | 'REVIEW_REQUIRED'
  | 'DUPLICATE'
  | 'EXCEPTION'
  | 'UNRESOLVED'

export interface RunSummary {
  run_id: string
  label: string
  created_at: string
  completed_at: string | null
  dataset_id: string
  dataset_mode: string
  status: string
  records_processed: number
  total_source_records: number
  deterministic_matches: number
  match_rate: number
  residuals: number
  exceptions: number
  unresolved: number
  exception_rate: number
  processing_time_ms: number
  throughput_rps: number
  total_reconciled_paisa: number
  total_expected_paisa: number
  total_actual_paisa: number
  total_variance_paisa: number
  unexplained_value_paisa: number
  engine_version: string
  status_distribution: Record<string, number>
  reason_code_distribution: Record<string, number>
  accounting_config: Record<string, number | string>
}

export interface RunComparison {
  baseline: RunSummary
  candidate: RunSummary
  deterministic_match_delta: number
  deterministic_match_improvement_pct: number
  match_rate_delta_pct: number
  residual_delta: number
  residual_reduction_pct: number
  exception_delta: number
  throughput_delta_rps: number
  processing_time_delta_ms: number
  unexplained_value_delta_paisa: number
  reason_code_deltas: Record<string, number>
}

export interface CalculationLine {
  label: string
  expression: string
  result_paisa: number
  rule_id: string
}

export interface EvidenceItem {
  source: string
  record_id: string
  fact: string
  amount_paisa: number | null
  detail: Record<string, unknown>
}

export interface Adjustment {
  adjustment_id: string
  type: string
  amount_paisa: number
  source_record: string
  related_payment: string | null
  related_settlement: string | null
  description: string
  evidence: EvidenceItem[]
}

export interface RecordSummary {
  reconciliation_id: string
  run_id: string
  status: ReconciliationStatus
  match_type: string
  confidence: number
  confidence_method: string
  order_id: string | null
  payment_id: string | null
  invoice_id: string | null
  settlement_ids: string[]
  bank_transaction_ids: string[]
  counterparty: string | null
  gross_amount_paisa: number
  expected_amount_paisa: number
  actual_amount_paisa: number
  variance_paisa: number
  unexplained_value_paisa: number
  reason_codes: string[]
  rule_ids: string[]
  value_date: string | null
  evidence_count: number
  requires_human_review: boolean
}

export interface RecordDetail extends RecordSummary {
  source_records: string[]
  calculation: CalculationLine[]
  evidence: EvidenceItem[]
  adjustments: Adjustment[]
  created_at: string
}

export interface ExceptionItem extends RecordSummary {
  headline: string
  findings: string[]
  resolution_status: string
  exposure_paisa: number
}

export interface AuditEvent {
  audit_id: string
  run_id: string
  timestamp: string
  action: string
  actor: string
  reconciliation_id: string | null
  rule_id: string | null
  calculation: string
  previous_state: string | null
  new_state: string | null
  source_records: string[]
  evidence: string[]
  detail: Record<string, unknown>
  system_version: string
}

export interface MetricsResponse {
  run: RunSummary | null
  status_distribution: Record<string, number>
  reason_code_distribution: Record<string, number>
  match_type_distribution: Record<string, number>
  confidence_distribution: Record<string, number>
  daily_volume: { date: string; matched: number; residual: number; value_paisa: number }[]
  top_exceptions_by_value: RecordSummary[]
  recent_runs: RunSummary[]
  formulas: Record<string, string>
}

export interface Rule {
  rule_id: string
  name: string
  description: string
  rule_type: string
  expression: string
  version: number
  status: string
  created_by: string
  created_at: string
  validation_count: number
  promoted_at: string | null
  is_dynamic: boolean
  parameters: Record<string, any>
  proposed_from_run?: string | null
  supporting_residuals?: string[]
  approved_by?: string | null
  decision_note?: string
}

export interface CashPosition {
  run_id: string | null
  confirmed_received_paisa: number
  committed_inflow_paisa: number
  at_risk_paisa: number
  unexplained_paisa: number
  lines: {
    value_date: string | null
    label: string
    amount_paisa: number
    basis: string
    source_records: string[]
  }[]
  basis: string
  includes_prediction: boolean
  forecast: unknown[]
  note: string
}

export interface Explanation {
  reconciliation_id: string
  run_id: string
  question: string
  verdict: string
  status: ReconciliationStatus
  match_type: string
  confidence: number
  confidence_method: string
  financial_calculation: CalculationLine[]
  source_records: string[]
  matching_logic: { layer: string; detail: string }[]
  evidence: EvidenceItem[]
  adjustments: Adjustment[]
  reason_codes: string[]
  rules_applied: string[]
  audit_events: Record<string, string>[]
  grounded: boolean
  generated_by: string
}

export interface ArbitrationQueue {
  run_id: string
  arbitrator: string
  ai_enabled: boolean
  queue_size: number
  residuals: {
    residual_id: string
    status: string
    reason_codes: string[]
    expected_amount_paisa: number
    actual_amount_paisa: number
    variance_paisa: number
    counterparty: string | null
    value_date: string | null
    source_records: string[]
    evidence_count: number
  }[]
  note: string
}

export interface Paged {
  total: number
  limit: number
  offset: number
  run_id: string
}

export interface RecordListResponse extends Paged {
  records: RecordSummary[]
}

export interface ExceptionListResponse extends Paged {
  exceptions: ExceptionItem[]
  summary: {
    total: number
    total_value_paisa: number
    unexplained_value_paisa: number
    by_reason_code: Record<string, { count: number; value_paisa: number }>
  }
}

export interface AuditListResponse {
  events: AuditEvent[]
  total: number
  limit: number
  offset: number
  run_id: string | null
  facets: { actions: string[]; rule_ids: string[]; actors: string[] }
}

export interface ResidualCandidate {
  candidate_id: string
  kind: string
  amount_paisa: number
  value_date: string | null
  counterparty: string | null
  source_records: string[]
  amount_delta_paisa: number
  date_delta_days: number | null
  amount_matches_exactly: boolean
  basis: string[]
}

export interface ModelMetadata {
  model?: string
  llm_confidence?: number
  evidence_confidence?: number
  final_confidence?: number
  auto_resolved?: boolean
  requires_human_review?: boolean
  evidence_breakdown?: {
    identifier: number
    amount: number
    date: number
    counterparty: number
  }
  [key: string]: unknown
}

export interface ArbitrationItem {
  residual_id: string
  run_id: string
  arbitrator: string
  uses_model: boolean
  decision: 'RESOLVE' | 'PROBABLE' | 'UNRESOLVED'
  confidence: number
  reason: string
  proposed_action: string | null
  evidence: string[]
  candidates: ResidualCandidate[]
  amount_paisa: number
  verification_accepted: boolean
  verification_reasons: string[]
  journal_batch: Record<string, unknown>
  requires_human_review: boolean
  model_metadata?: ModelMetadata
  created_at: string
}

export interface ArbitrationSummary {
  total: number
  decisions: Record<string, number>
  accepted: number
  rejected_by_verification: number
  uses_model: boolean
  arbitrator: string
  total_tokens?: number
  estimated_cost_usd?: number
  auto_resolved_count?: number
  human_review_count?: number
  rules_proposed_count?: number
}

export interface ArbitrationRunResult {
  run_id: string
  arbitrator: string
  uses_model: boolean
  residuals_examined: number
  proposals: ArbitrationItem[]
  journal_entries_proposed: number
  rule_proposals: {
    rule_id: string
    name: string
    description: string
    rule_type: string
    expression: string
    support: number
    parameters: Record<string, unknown>
  }[]
  summary: ArbitrationSummary
}

export interface ArbitrationListResponse {
  run_id: string
  items: ArbitrationItem[]
  total: number
  summary: ArbitrationSummary
}

export interface EvaluationMetrics {
  run_id: string
  total_residuals: number
  evaluated_residuals: number
  correct_decisions: number
  incorrect_decisions: number
  overrides_prevented: number
  precision: number
  recall: number
  f1_score: number
  accuracy: number
  coverage: number
  confusion_matrix: Record<string, Record<string, number>>
}

export interface RuleValidation {
  validation_id: string
  rule_id: string
  dataset_id: string
  baseline_matches: number
  candidate_matches: number
  match_delta: number
  baseline_residuals: number
  candidate_residuals: number
  residual_delta: number
  baseline_match_rate: number
  candidate_match_rate: number
  match_rate_delta_pct: number
  regressions: string[]
  verdict: 'IMPROVES' | 'REGRESSES' | 'NEUTRAL' | 'INVALID'
  created_at: string
  detail: Record<string, unknown>
}

export interface RuleCatalogue {
  rules: Rule[]
  total: number
  by_status: Record<string, number>
  active_dynamic_rules: string[]
  validations: RuleValidation[]
  lifecycle: { status: string; note: string }[]
  note: string
}

export interface RuleDemoResponse {
  status: string
  dataset_id: string
  baseline_run_id: string
  self_healed_run_id: string
  promoted_rule_id: string | null
  promoted_rule_name: string
  baseline_matches: number
  after_matches: number
  matches_added: number
  baseline_residuals: number
  after_residuals: number
  residual_reduction: number
  ai_dependency_reduction_pct: number
  deterministic_coverage_before_pct: number
  deterministic_coverage_after_pct: number
  estimated_ai_cost_avoided_usd: number
  message: string
}

export interface JournalEntry {
  journal_id: string
  batch_id: string
  run_id: string
  residual_id: string
  entry_date: string
  debit_account: string
  debit_account_name: string
  credit_account: string
  credit_account_name: string
  amount_paisa: number
  description: string
  source_records: string[]
  confidence: number
  status: 'DRAFT' | 'PROPOSED' | 'APPROVED' | 'POSTED' | 'REJECTED'
  proposed_by: string
  decided_by: string | null
  decided_at: string | null
  created_at: string
}

export interface JournalListResponse {
  entries: JournalEntry[]
  total: number
  limit: number
  offset: number
  by_status: Record<string, number>
  total_proposed_paisa: number
  chart_of_accounts: { code: string; name: string; account_type: string; description: string }[]
}

export interface TrialBalance {
  run_id: string | null
  posted_entries: number
  total_debits_paisa: number
  total_credits_paisa: number
  balanced: boolean
  accounts: {
    code: string
    name: string
    account_type: string
    debit_paisa: number
    credit_paisa: number
    balance_paisa: number
  }[]
}

export interface ForecastPoint {
  value_date: string
  expected_inflow_paisa: number
  low_paisa: number
  high_paisa: number
  committed_paisa: number
  projected_paisa: number
  method: string
  confidence: number
  basis: string
  source_records: string[]
}

export interface ForecastResponse {
  run_id: string
  horizon_days: number
  method: string
  committed_total_paisa: number
  projected_total_paisa: number
  expected_total_paisa: number
  backtest: {
    train_days: number
    test_days: number
    hits: number
    coverage: number
    median_paisa: number
    low_paisa: number
    high_paisa: number
    usable: boolean
    note: string
  } | null
  points: ForecastPoint[]
  note: string
}

export interface CopilotFact {
  label: string
  value: string
}

export interface CopilotCitation {
  source: string
  record_id: string
}

export interface CopilotAnswer {
  question: string
  intent: string
  answer: string
  why?: string
  financial_impact?: string
  risk?: string
  recommended_action?: string
  confidence?: number
  confidence_method?: string
  facts: CopilotFact[]
  citations?: CopilotCitation[]
  records: string[]
  grounded: boolean
  generated_by: string
  followups: string[]
  detail: Record<string, unknown>
}

export interface CashResiliencePoint {
  week_number: number
  start_date: string
  end_date: string
  opening_cash_paisa: number
  confirmed_inflow_paisa: number
  expected_settlement_inflow_paisa: number
  total_inflow_paisa: number
  refunds_paisa: number
  chargebacks_paisa: number
  taxes_paisa: number
  payroll_paisa: number
  operating_expenses_paisa: number
  total_outflow_paisa: number
  net_cash_flow_paisa: number
  p10_closing_cash_paisa: number
  p50_closing_cash_paisa: number
  p90_closing_cash_paisa: number
  major_risk: string | null
  source_records: string[]
}

export interface PayrollRiskAnalysis {
  payroll_requirement_paisa: number
  payroll_date: string
  p10_projected_cash_paisa: number
  p50_projected_cash_paisa: number
  p90_projected_cash_paisa: number
  shortfall_under_p10_paisa: number
  risk_level: 'HIGH' | 'MEDIUM' | 'LOW'
  primary_driver: string
  explanation: string
  evidence_records: string[]
}

export interface RiskIndicator {
  risk_id: string
  severity: 'CRITICAL' | 'WARNING' | 'INFO'
  category: string
  amount_paisa: number
  date: string | null
  explanation: string
  evidence: string[]
  source_records: string[]
}

export interface RiskIntervention {
  intervention_id: string
  risk_id: string
  type: 'PRIMARY_RECOMMENDATION' | 'SECONDARY_OPTION'
  fact: string
  recommendation: string
  potential_impact_paisa: number
}

export interface CashResilienceResponse {
  run_id: string
  as_of: string
  current_cash_paisa: number
  outlook_13w_paisa: number
  at_risk_cash_paisa: number
  next_major_obligation: { label: string; amount_paisa: number; due_date: string }
  confirmed_cash_paisa: number
  expected_cash_paisa: number
  unresolved_cash_paisa: number
  payroll_risk: PayrollRiskAnalysis
  weekly_points: CashResiliencePoint[]
  risks: RiskIndicator[]
  interventions: RiskIntervention[]
  note: string
}

export interface Health {
  status: string
  database: string
  reconciliation_engine: string
  ai_provider: string
  version: string
  accounting: Record<string, any>
  engine_version: string
}

export interface HealthResponse extends Health {
  ai_status?: string
}
