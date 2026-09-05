"""ORM entities.

Deliberate design choices:

* Money is BigInteger paise everywhere. No float, no numeric.
* Evidence, calculations and reason codes are stored as JSON on the record
  rather than normalised away, because they are an immutable snapshot of what
  the engine proved at run time. Re-deriving them later from a changed engine
  would silently rewrite history, which is the opposite of an audit trail.
* Audit events are append-only. Nothing in the application updates or deletes
  a row in this table.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ReconciliationRun(Base):
    """One execution of the engine. All metrics are measured, never assumed."""

    __tablename__ = "reconciliation_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_source_records: Mapped[int] = mapped_column(Integer, default=0)
    deterministic_matches: Mapped[int] = mapped_column(Integer, default=0)
    partial_matches: Mapped[int] = mapped_column(Integer, default=0)
    review_required: Mapped[int] = mapped_column(Integer, default=0)
    exceptions: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    unresolved: Mapped[int] = mapped_column(Integer, default=0)
    residuals: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    throughput_rps: Mapped[float] = mapped_column(Float, default=0.0)
    match_rate: Mapped[float] = mapped_column(Float, default=0.0)
    exception_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_reconciled_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    total_variance_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    unexplained_value_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    engine_version: Mapped[str] = mapped_column(String(64), default="")
    dataset_id: Mapped[str] = mapped_column(String(64), default="")
    dataset_mode: Mapped[str] = mapped_column(String(16), default="")
    status_distribution: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    reason_code_distribution: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    accounting_config: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    label: Mapped[str] = mapped_column(String(120), default="")

    records: Mapped[List["ReconciliationRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    events: Mapped[List["AuditEventRow"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ReconciliationRecord(Base):
    """One reconciliation decision, with its proof attached."""

    __tablename__ = "reconciliation_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reconciliation_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.run_id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    match_type: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_method: Mapped[str] = mapped_column(String(64), default="")

    expected_amount_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    actual_amount_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    variance_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    gross_amount_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    unexplained_value_paisa: Mapped[int] = mapped_column(BigInteger, default=0)

    order_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    payment_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    counterparty: Mapped[Optional[str]] = mapped_column(String(160))
    value_date: Mapped[Optional[date]] = mapped_column(Date)

    source_records: Mapped[List[str]] = mapped_column(JSON, default=list)
    settlement_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    bank_transaction_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    reason_codes: Mapped[List[str]] = mapped_column(JSON, default=list)
    calculation: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    adjustments: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    rule_ids: Mapped[List[str]] = mapped_column(JSON, default=list)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    run: Mapped[ReconciliationRun] = relationship(back_populates="records")


Index(
    "ix_records_run_status",
    ReconciliationRecord.run_id,
    ReconciliationRecord.status,
)


class AuditEventRow(Base):
    """Append-only. No code path in this application updates or deletes here."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("reconciliation_runs.run_id", ondelete="CASCADE"), nullable=True, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    actor: Mapped[str] = mapped_column(String(64), default="")
    reconciliation_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    rule_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    calculation: Mapped[str] = mapped_column(Text, default="")
    previous_state: Mapped[Optional[str]] = mapped_column(String(32))
    new_state: Mapped[Optional[str]] = mapped_column(String(32))
    source_records: Mapped[List[str]] = mapped_column(JSON, default=list)
    evidence: Mapped[List[str]] = mapped_column(JSON, default=list)
    detail: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    system_version: Mapped[str] = mapped_column(String(48), default="")

    run: Mapped[Optional[ReconciliationRun]] = relationship(back_populates="events")


class RuleRow(Base):
    """Rule registry. Promotion is manual by design in this phase."""

    __tablename__ = "rules"

    rule_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    rule_type: Mapped[str] = mapped_column(String(32), index=True)
    expression: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), index=True)
    created_by: Mapped[str] = mapped_column(String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    validation_count: Mapped[int] = mapped_column(Integer, default=0)
    promoted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    #: Executable configuration for a dynamic rule. Built-in rules leave this
    #: empty: they are compiled into the engine and described here only so the
    #: catalogue is complete.
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Provenance for a proposed rule: which run and which residuals motivated it.
    proposed_from_run: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    supporting_residuals: Mapped[List[str]] = mapped_column(JSON, default=list)
    decision_note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    #: Phase 3 metrics & approval tracking
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    backtest_result: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_match_gain: Mapped[int] = mapped_column(Integer, default=0)
    expected_false_positive_rate: Mapped[float] = mapped_column(Float, default=0.0)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetRow(Base):
    """Registry of generated datasets so runs can name their input."""

    __tablename__ = "datasets"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16))
    seed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    manifest: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class ArbitrationRow(Base):
    """One arbitration proposal and the verdict of the verification gate.

    Rejected proposals are stored, not discarded. What an arbitrator got wrong
    is exactly the evidence needed to decide whether to keep trusting it.
    """

    __tablename__ = "arbitration_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    residual_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.run_id", ondelete="CASCADE"), index=True
    )
    arbitrator: Mapped[str] = mapped_column(String(96), index=True)
    uses_model: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[str] = mapped_column(String(24), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    proposed_action: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    evidence: Mapped[List[str]] = mapped_column(JSON, default=list)
    candidates: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    amount_paisa: Mapped[int] = mapped_column(BigInteger, default=0)

    verification_accepted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verification_reasons: Mapped[List[str]] = mapped_column(JSON, default=list)
    journal_batch: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    model_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalEntryRow(Base):
    """A proposed or posted double-entry line."""

    __tablename__ = "journal_entries"

    journal_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(48), index=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.run_id", ondelete="CASCADE"), index=True
    )
    residual_id: Mapped[str] = mapped_column(String(32), index=True)
    entry_date: Mapped[date] = mapped_column(Date)
    debit_account: Mapped[str] = mapped_column(String(16), index=True)
    credit_account: Mapped[str] = mapped_column(String(16), index=True)
    amount_paisa: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    source_records: Mapped[List[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), index=True)
    proposed_by: Mapped[str] = mapped_column(String(96), default="")
    decided_by: Mapped[Optional[str]] = mapped_column(String(96))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RuleValidationRow(Base):
    """The measured effect of replaying a proposed rule over a dataset.

    This is what promotion is decided on. A rule is promoted because a replay
    showed it helped, not because a model was confident about it.
    """

    __tablename__ = "rule_validations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_id: Mapped[str] = mapped_column(String(32), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    baseline_matches: Mapped[int] = mapped_column(Integer, default=0)
    candidate_matches: Mapped[int] = mapped_column(Integer, default=0)
    match_delta: Mapped[int] = mapped_column(Integer, default=0)
    baseline_residuals: Mapped[int] = mapped_column(Integer, default=0)
    candidate_residuals: Mapped[int] = mapped_column(Integer, default=0)
    residual_delta: Mapped[int] = mapped_column(Integer, default=0)
    baseline_match_rate: Mapped[float] = mapped_column(Float, default=0.0)
    candidate_match_rate: Mapped[float] = mapped_column(Float, default=0.0)
    regressions: Mapped[List[str]] = mapped_column(JSON, default=list)
    verdict: Mapped[str] = mapped_column(String(24), index=True)
    detail: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CopilotQueryAuditRow(Base):
    """Audit log for material Copilot queries and grounded financial responses."""

    __tablename__ = "copilot_query_audits"

    query_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(48), index=True)
    question: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(48), index=True)
    answer: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    confidence_method: Mapped[str] = mapped_column(String(32), default="DETERMINISTIC")
    facts: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    citations: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    verification_passed: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[str] = mapped_column(String(96), default="finance_user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
