"""Pydantic response models for the API surface.

Money crosses the wire as integer paise under a ``_paisa`` suffixed name, with
a formatted display string alongside where the UI needs one. The frontend never
does money arithmetic on a float.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    system_version: str
    engine_version: str
    database: str
    ai_provider: str
    ai_enabled: bool
    deterministic_engine_requires_ai: bool = False
    accounting: Dict[str, Any]
    dataset_available: bool
    latest_run_id: Optional[str] = None


class GenerateDataRequest(BaseModel):
    order_count: int = Field(default=500, ge=1, le=100_000)
    seed: int = 42
    mode: str = Field(default="messy", pattern="^(clean|messy)$")
    dataset_id: Optional[str] = None


class GenerateDataResponse(BaseModel):
    dataset_id: str
    mode: str
    seed: int
    manifest: Dict[str, Any]
    anomaly_breakdown: Dict[str, int]
    written_to: str


class RunRequest(BaseModel):
    dataset_id: Optional[str] = None
    label: str = ""


class RunSummary(BaseModel):
    run_id: str
    label: str = ""
    started_at: datetime
    completed_at: datetime
    records_processed: int
    total_source_records: int
    deterministic_matches: int
    partial_matches: int
    review_required: int
    exceptions: int
    duplicates: int
    unresolved: int
    residuals: int
    processing_time_ms: float
    throughput_rps: float
    match_rate: float
    exception_rate: float
    total_reconciled_paisa: int
    total_variance_paisa: int
    unexplained_value_paisa: int
    engine_version: str
    dataset_id: str
    dataset_mode: str
    status_distribution: Dict[str, int] = {}
    reason_code_distribution: Dict[str, int] = {}
    accounting_config: Dict[str, Any] = {}


class RunListResponse(BaseModel):
    runs: List[RunSummary]
    total: int


class RunComparison(BaseModel):
    baseline: RunSummary
    candidate: RunSummary
    deterministic_match_delta: int
    deterministic_match_improvement_pct: float
    match_rate_delta_pct: float
    residual_delta: int
    residual_reduction_pct: float
    exception_delta: int
    throughput_delta_rps: float
    processing_time_delta_ms: float
    unexplained_value_delta_paisa: int
    reason_code_deltas: Dict[str, int]


class CalculationLineOut(BaseModel):
    label: str
    expression: str
    result_paisa: int
    rule_id: str


class EvidenceOut(BaseModel):
    source: str
    record_id: str
    fact: str
    amount_paisa: Optional[int] = None
    detail: Dict[str, Any] = {}


class RecordSummary(BaseModel):
    reconciliation_id: str
    run_id: str
    status: str
    match_type: str
    confidence: float
    confidence_method: str
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    invoice_id: Optional[str] = None
    settlement_ids: List[str] = []
    bank_transaction_ids: List[str] = []
    counterparty: Optional[str] = None
    gross_amount_paisa: int
    expected_amount_paisa: int
    actual_amount_paisa: int
    variance_paisa: int
    unexplained_value_paisa: int
    reason_codes: List[str] = []
    rule_ids: List[str] = []
    value_date: Optional[date] = None
    evidence_count: int = 0
    requires_human_review: bool = False


class RecordDetail(RecordSummary):
    source_records: List[str] = []
    calculation: List[CalculationLineOut] = []
    evidence: List[EvidenceOut] = []
    adjustments: List[Dict[str, Any]] = []
    created_at: datetime


class RecordListResponse(BaseModel):
    records: List[RecordSummary]
    total: int
    limit: int
    offset: int
    run_id: str


class ExceptionItem(RecordSummary):
    headline: str
    findings: List[str] = []
    resolution_status: str = "HUMAN REVIEW REQUIRED"
    #: Money at stake. Not the same as variance: a PARTIAL_MATCH has zero
    #: variance but the full payout is still outstanding.
    exposure_paisa: int = 0


class ExceptionListResponse(BaseModel):
    exceptions: List[ExceptionItem]
    total: int
    limit: int
    offset: int
    run_id: str
    summary: Dict[str, Any] = {}


class AuditEventOut(BaseModel):
    audit_id: str
    run_id: str
    timestamp: datetime
    action: str
    actor: str
    reconciliation_id: Optional[str] = None
    rule_id: Optional[str] = None
    calculation: str = ""
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    source_records: List[str] = []
    evidence: List[str] = []
    detail: Dict[str, Any] = {}
    system_version: str = ""


class AuditListResponse(BaseModel):
    events: List[AuditEventOut]
    total: int
    limit: int
    offset: int
    run_id: Optional[str] = None
    facets: Dict[str, List[str]] = {}


class MetricsResponse(BaseModel):
    run: Optional[RunSummary] = None
    status_distribution: Dict[str, int] = {}
    reason_code_distribution: Dict[str, int] = {}
    match_type_distribution: Dict[str, int] = {}
    confidence_distribution: Dict[str, int] = {}
    daily_volume: List[Dict[str, Any]] = []
    top_exceptions_by_value: List[Dict[str, Any]] = []
    recent_runs: List[RunSummary] = []
    formulas: Dict[str, str] = {}


class RuleOut(BaseModel):
    rule_id: str
    name: str
    description: str
    rule_type: str
    expression: str
    version: int
    status: str
    created_by: str
    created_at: datetime
    validation_count: int
    promoted_at: Optional[datetime] = None


class RuleListResponse(BaseModel):
    rules: List[RuleOut]
    total: int
    by_status: Dict[str, int] = {}
    promotion_enabled: bool = False
    note: str = ""


class CashPositionResponse(BaseModel):
    run_id: Optional[str] = None
    confirmed_received_paisa: int = 0
    committed_inflow_paisa: int = 0
    at_risk_paisa: int = 0
    unexplained_paisa: int = 0
    lines: List[Dict[str, Any]] = []
    basis: str = "deterministic"
    includes_prediction: bool = False
    forecast: List[Dict[str, Any]] = []
    note: str = ""


class ExplainResponse(BaseModel):
    reconciliation_id: str
    run_id: str
    question: str
    verdict: str
    status: str
    match_type: str
    confidence: float
    confidence_method: str
    financial_calculation: List[Dict[str, Any]] = []
    source_records: List[str] = []
    matching_logic: List[Dict[str, str]] = []
    evidence: List[Dict[str, Any]] = []
    adjustments: List[Dict[str, Any]] = []
    reason_codes: List[str] = []
    rules_applied: List[str] = []
    audit_events: List[Dict[str, Any]] = []
    grounded: bool = True
    generated_by: str = "deterministic-retrieval"


class ArbitrationQueueResponse(BaseModel):
    run_id: str
    arbitrator: str
    ai_enabled: bool
    queue_size: int
    residuals: List[Dict[str, Any]] = []
    note: str = ""


# ---------------------------------------------------------------------------
# Phase 2: arbitration, rule promotion, journals, forecasting, copilot
# ---------------------------------------------------------------------------


class ArbitrateRequest(BaseModel):
    run_id: Optional[str] = None
    #: Override the configured arbitrator for this call. "deterministic" needs
    #: no credentials; "anthropic"/"openai" fall back if unreachable.
    arbitrator: Optional[str] = None
    propose_rules: bool = True
    limit: int = Field(default=1000, ge=1, le=10_000)


class ArbitrationRunResponse(BaseModel):
    run_id: str
    arbitrator: str
    uses_model: bool
    residuals_examined: int
    accepted: int
    rejected_by_verification: int
    decisions: Dict[str, int] = {}
    journal_entries_proposed: int = 0
    rule_proposals: List[Dict[str, Any]] = []


class ArbitrationItem(BaseModel):
    residual_id: str
    run_id: str
    arbitrator: str
    uses_model: bool
    decision: str
    confidence: float
    reason: str
    proposed_action: Optional[str] = None
    evidence: List[str] = []
    candidates: List[Dict[str, Any]] = []
    amount_paisa: int
    verification_accepted: bool
    verification_reasons: List[str] = []
    journal_batch: Dict[str, Any] = {}
    requires_human_review: bool
    created_at: datetime


class ArbitrationListResponse(BaseModel):
    run_id: str
    items: List[ArbitrationItem] = []
    total: int
    summary: Dict[str, Any] = {}


class RuleDetail(RuleOut):
    parameters: Dict[str, Any] = {}
    proposed_from_run: Optional[str] = None
    supporting_residuals: List[str] = []
    decision_note: str = ""
    updated_at: Optional[datetime] = None
    is_dynamic: bool = False


class RuleValidationOut(BaseModel):
    validation_id: str
    rule_id: str
    dataset_id: str
    baseline_matches: int
    candidate_matches: int
    match_delta: int
    baseline_residuals: int
    candidate_residuals: int
    residual_delta: int
    baseline_match_rate: float
    candidate_match_rate: float
    match_rate_delta_pct: float
    regressions: List[str] = []
    verdict: str
    detail: Dict[str, Any] = {}
    created_at: datetime


class RuleCatalogueResponse(BaseModel):
    rules: List[RuleDetail]
    total: int
    by_status: Dict[str, int] = {}
    active_dynamic_rules: List[str] = []
    validations: List[RuleValidationOut] = []
    lifecycle: List[Dict[str, str]] = []
    note: str = ""


class RuleValidateRequest(BaseModel):
    dataset_id: Optional[str] = None


class RuleDecisionRequest(BaseModel):
    #: Mandatory. Promotion changes what the engine matches, so it is attributed.
    actor: str = Field(min_length=1)
    note: str = ""


class JournalEntryOut(BaseModel):
    journal_id: str
    batch_id: str
    run_id: str
    residual_id: str
    entry_date: date
    debit_account: str
    debit_account_name: str
    credit_account: str
    credit_account_name: str
    amount_paisa: int
    description: str
    source_records: List[str] = []
    confidence: float
    status: str
    proposed_by: str = ""
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime


class JournalListResponse(BaseModel):
    entries: List[JournalEntryOut] = []
    total: int
    limit: int
    offset: int
    by_status: Dict[str, int] = {}
    total_proposed_paisa: int = 0
    chart_of_accounts: List[Dict[str, str]] = []


class JournalDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT|POST|approve|reject|post)$")
    actor: str = Field(min_length=1)
    note: str = ""


class TrialBalanceResponse(BaseModel):
    run_id: Optional[str] = None
    posted_entries: int
    total_debits_paisa: int
    total_credits_paisa: int
    balanced: bool
    accounts: List[Dict[str, Any]] = []


class ForecastResponse(BaseModel):
    run_id: str
    horizon_days: int
    method: str
    committed_total_paisa: int
    projected_total_paisa: int
    expected_total_paisa: int
    backtest: Optional[Dict[str, Any]] = None
    points: List[Dict[str, Any]] = []
    note: str = ""


class CashResilienceResponse(BaseModel):
    run_id: str
    as_of: str
    current_cash_paisa: int
    outlook_13w_paisa: int
    at_risk_cash_paisa: int
    next_major_obligation: Dict[str, Any] = {}
    confirmed_cash_paisa: int
    expected_cash_paisa: int
    unresolved_cash_paisa: int
    payroll_risk: Dict[str, Any] = {}
    weekly_points: List[Dict[str, Any]] = []
    risks: List[Dict[str, Any]] = []
    interventions: List[Dict[str, Any]] = []
    note: str = ""


class CopilotRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    run_id: Optional[str] = None


class CopilotResponse(BaseModel):
    question: str
    intent: str
    answer: str
    why: str = ""
    financial_impact: str = ""
    risk: str = ""
    recommended_action: str = ""
    confidence: float = 1.0
    confidence_method: str = "DETERMINISTIC"
    facts: List[Dict[str, Any]] = []
    citations: List[Dict[str, str]] = []
    records: List[str] = []
    grounded: bool = True
    generated_by: str = "deterministic-retrieval"
    followups: List[str] = []
    detail: Dict[str, Any] = {}
