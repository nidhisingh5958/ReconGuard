"""Reconciliation result model - the core output contract of the engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.enums import (
    AdjustmentType,
    ConfidenceMethod,
    MatchType,
    ReasonCode,
    ReconciliationStatus,
)


@dataclass(slots=True)
class CalculationLine:
    """One line of a shown-work accounting derivation.

    ``expression`` is the literal arithmetic with real numbers substituted, so
    the UI can render the exact calculation rather than a templated sentence.
    """

    label: str
    expression: str
    result_paisa: int
    rule_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "expression": self.expression,
            "result_paisa": self.result_paisa,
            "rule_id": self.rule_id,
        }


@dataclass(slots=True)
class Evidence:
    """A pointer to a real source record plus the fact it establishes.

    Evidence is only ever constructed from data that exists. Nothing here is
    synthesised to make a result look better supported than it is.
    """

    source: str
    record_id: str
    fact: str
    amount_paisa: Optional[int] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "record_id": self.record_id,
            "fact": self.fact,
            "amount_paisa": self.amount_paisa,
            "detail": self.detail,
        }


@dataclass(slots=True)
class AdjustmentRecord:
    """A verified non-payment movement inside a settlement (refund, chargeback).

    Its existence is what stops a netted refund being misreported as a missing
    order.
    """

    adjustment_id: str
    adjustment_type: AdjustmentType
    amount_paisa: int
    source_record: str
    related_payment: Optional[str]
    related_settlement: Optional[str]
    evidence: List[Evidence] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adjustment_id": self.adjustment_id,
            "type": self.adjustment_type.value,
            "amount_paisa": self.amount_paisa,
            "source_record": self.source_record,
            "related_payment": self.related_payment,
            "related_settlement": self.related_settlement,
            "description": self.description,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass(slots=True)
class ReconciliationResult:
    reconciliation_id: str
    status: ReconciliationStatus
    match_type: MatchType
    confidence: float
    confidence_method: ConfidenceMethod
    source_records: List[str] = field(default_factory=list)
    expected_amount_paisa: int = 0
    actual_amount_paisa: int = 0
    variance_paisa: int = 0
    reason_codes: List[ReasonCode] = field(default_factory=list)
    calculation: List[CalculationLine] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    adjustments: List[AdjustmentRecord] = field(default_factory=list)
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    settlement_ids: List[str] = field(default_factory=list)
    bank_transaction_ids: List[str] = field(default_factory=list)
    invoice_id: Optional[str] = None
    counterparty: Optional[str] = None
    gross_amount_paisa: int = 0
    value_date: Optional[date] = None
    rule_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_matched(self) -> bool:
        return self.status is ReconciliationStatus.MATCHED

    @property
    def unexplained_value_paisa(self) -> int:
        """Money we cannot account for. Matched rows contribute zero by definition."""
        if self.status is ReconciliationStatus.MATCHED:
            return 0
        if self.variance_paisa:
            return abs(self.variance_paisa)
        return abs(self.expected_amount_paisa - self.actual_amount_paisa)


@dataclass(slots=True)
class RunMetrics:
    """Computed from an actual run. Never hardcoded, never estimated."""

    run_id: str
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
