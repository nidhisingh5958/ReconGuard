"""Persistence and query access for runs, records and audit events.

The engine has no idea this module exists. It returns plain domain objects and
this layer decides how to store them, which is what keeps the engine testable
without a database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.audit import AuditEvent
from app.domain.enums import ReconciliationStatus
from app.domain.reconciliation import ReconciliationResult, RunMetrics
from app.models.entities import (
    AuditEventRow,
    DatasetRow,
    ReconciliationRecord,
    ReconciliationRun,
)
from app.services.metrics.calculator import (
    reason_code_distribution,
    status_distribution,
)
from app.services.reconciliation.classification import requires_human_review


def next_run_id(session: Session) -> str:
    """Sequential, human-readable run ids: RUN-00001, RUN-00002, ..."""
    count = session.scalar(select(func.count()).select_from(ReconciliationRun)) or 0
    candidate = count + 1
    existing = {r[0] for r in session.execute(select(ReconciliationRun.run_id)).all()}
    while f"RUN-{candidate:05d}" in existing:
        candidate += 1
    return f"RUN-{candidate:05d}"


def _record_to_row(
    result: ReconciliationResult, run_id: str
) -> ReconciliationRecord:
    return ReconciliationRecord(
        reconciliation_id=result.reconciliation_id,
        run_id=run_id,
        status=result.status.value,
        match_type=result.match_type.value,
        confidence=result.confidence,
        confidence_method=result.confidence_method.value,
        expected_amount_paisa=result.expected_amount_paisa,
        actual_amount_paisa=result.actual_amount_paisa,
        variance_paisa=result.variance_paisa,
        gross_amount_paisa=result.gross_amount_paisa,
        unexplained_value_paisa=result.unexplained_value_paisa,
        order_id=result.order_id,
        payment_id=result.payment_id,
        invoice_id=result.invoice_id,
        counterparty=result.counterparty,
        value_date=result.value_date,
        source_records=list(result.source_records),
        settlement_ids=list(result.settlement_ids),
        bank_transaction_ids=list(result.bank_transaction_ids),
        reason_codes=[c.value for c in result.reason_codes],
        calculation=[line.to_dict() for line in result.calculation],
        evidence=[e.to_dict() for e in result.evidence],
        adjustments=[a.to_dict() for a in result.adjustments],
        rule_ids=list(result.rule_ids),
        requires_human_review=requires_human_review(result.status),
        created_at=result.created_at,
    )


def _audit_to_row(event: AuditEvent, run_id: str) -> AuditEventRow:
    return AuditEventRow(
        audit_id=event.audit_id,
        run_id=run_id,
        timestamp=event.timestamp,
        action=event.action.value,
        actor=event.actor,
        reconciliation_id=event.reconciliation_id,
        rule_id=event.rule_id,
        calculation=event.calculation,
        previous_state=event.previous_state,
        new_state=event.new_state,
        source_records=list(event.source_records),
        evidence=list(event.evidence),
        detail=dict(event.detail),
        system_version=event.system_version,
    )


def save_run(
    session: Session,
    metrics: RunMetrics,
    results: Sequence[ReconciliationResult],
    audit_events: Sequence[AuditEvent],
    accounting_config: Dict[str, Any],
    label: str = "",
) -> ReconciliationRun:
    """Persist an entire run atomically."""
    run = ReconciliationRun(
        run_id=metrics.run_id,
        started_at=metrics.started_at,
        completed_at=metrics.completed_at,
        records_processed=metrics.records_processed,
        total_source_records=metrics.total_source_records,
        deterministic_matches=metrics.deterministic_matches,
        partial_matches=metrics.partial_matches,
        review_required=metrics.review_required,
        exceptions=metrics.exceptions,
        duplicates=metrics.duplicates,
        unresolved=metrics.unresolved,
        residuals=metrics.residuals,
        processing_time_ms=metrics.processing_time_ms,
        throughput_rps=metrics.throughput_rps,
        match_rate=metrics.match_rate,
        exception_rate=metrics.exception_rate,
        total_reconciled_paisa=metrics.total_reconciled_paisa,
        total_variance_paisa=metrics.total_variance_paisa,
        unexplained_value_paisa=metrics.unexplained_value_paisa,
        engine_version=metrics.engine_version,
        dataset_id=metrics.dataset_id,
        dataset_mode=metrics.dataset_mode,
        status_distribution=status_distribution(results),
        reason_code_distribution=reason_code_distribution(results),
        accounting_config=accounting_config,
        label=label,
    )
    session.add(run)
    session.add_all(_record_to_row(r, metrics.run_id) for r in results)
    session.add_all(_audit_to_row(e, metrics.run_id) for e in audit_events)
    session.commit()
    return run


def latest_run(session: Session) -> Optional[ReconciliationRun]:
    return session.scalar(
        select(ReconciliationRun).order_by(ReconciliationRun.started_at.desc()).limit(1)
    )


def get_run(session: Session, run_id: str) -> Optional[ReconciliationRun]:
    return session.get(ReconciliationRun, run_id)


def list_runs(session: Session, limit: int = 50) -> List[ReconciliationRun]:
    return list(
        session.scalars(
            select(ReconciliationRun)
            .order_by(ReconciliationRun.started_at.desc())
            .limit(limit)
        ).all()
    )


def resolve_run_id(session: Session, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return run_id
    run = latest_run(session)
    return run.run_id if run else None


def query_records(
    session: Session,
    run_id: str,
    status: Optional[str] = None,
    statuses: Optional[Sequence[str]] = None,
    match_type: Optional[str] = None,
    reason_code: Optional[str] = None,
    search: Optional[str] = None,
    min_variance_paisa: Optional[int] = None,
    order_by: str = "reconciliation_id",
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[ReconciliationRecord], int]:
    """Filtered, paginated record query. Returns (rows, total_matching).

    ``order_by`` is applied BEFORE pagination. That ordering is load-bearing
    for the exception desk: sorting only the current page would mean the first
    page of "largest exposure" was not actually the largest.
    """
    stmt = select(ReconciliationRecord).where(ReconciliationRecord.run_id == run_id)

    if status:
        stmt = stmt.where(ReconciliationRecord.status == status)
    if statuses:
        stmt = stmt.where(ReconciliationRecord.status.in_(list(statuses)))
    if match_type:
        stmt = stmt.where(ReconciliationRecord.match_type == match_type)
    if search:
        needle = f"%{search.strip().upper()}%"
        stmt = stmt.where(
            func.upper(ReconciliationRecord.order_id).like(needle)
            | func.upper(ReconciliationRecord.payment_id).like(needle)
            | func.upper(ReconciliationRecord.invoice_id).like(needle)
            | func.upper(ReconciliationRecord.counterparty).like(needle)
            | func.upper(ReconciliationRecord.reconciliation_id).like(needle)
        )
    if min_variance_paisa is not None:
        stmt = stmt.where(
            func.abs(ReconciliationRecord.variance_paisa) >= min_variance_paisa
        )

    rows = list(session.scalars(stmt).all())

    # Reason codes live in a JSON array. Filtering them in Python keeps the
    # query portable across SQLite and PostgreSQL, and the working set here is
    # one run's records, which is bounded and already in memory.
    if reason_code:
        rows = [r for r in rows if reason_code in (r.reason_codes or [])]

    total = len(rows)
    if order_by == "exposure_desc":
        rows.sort(key=lambda r: (-exposure_paisa(r), r.reconciliation_id))
    else:
        rows.sort(key=lambda r: r.reconciliation_id)
    return rows[offset : offset + limit], total


def exposure_paisa(record: ReconciliationRecord) -> int:
    """Money this record puts at stake, which is not the same as variance.

    A PARTIAL_MATCH has zero variance (the settlement arithmetic is provably
    correct) yet the cash has not arrived, so its exposure is the full amount
    awaited. Ranking the exception desk by variance alone would push exactly
    those rows to the bottom.
    """
    if record.status == "PARTIAL_MATCH":
        return abs(record.expected_amount_paisa)
    if record.status in ("DUPLICATE", "REVIEW_REQUIRED"):
        return abs(record.variance_paisa) or abs(record.unexplained_value_paisa)
    return abs(record.unexplained_value_paisa)


def get_record(
    session: Session, reconciliation_id: str, run_id: Optional[str] = None
) -> Optional[ReconciliationRecord]:
    stmt = select(ReconciliationRecord).where(
        ReconciliationRecord.reconciliation_id == reconciliation_id
    )
    if run_id:
        stmt = stmt.where(ReconciliationRecord.run_id == run_id)
    return session.scalars(stmt.order_by(ReconciliationRecord.id.desc())).first()


def query_audit_events(
    session: Session,
    run_id: Optional[str] = None,
    reconciliation_id: Optional[str] = None,
    action: Optional[str] = None,
    rule_id: Optional[str] = None,
    actor: Optional[str] = None,
    new_state: Optional[str] = None,
    source_record: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 200,
    offset: int = 0,
) -> Tuple[List[AuditEventRow], int]:
    stmt = select(AuditEventRow)
    if run_id:
        stmt = stmt.where(AuditEventRow.run_id == run_id)
    if reconciliation_id:
        stmt = stmt.where(AuditEventRow.reconciliation_id == reconciliation_id)
    if action:
        stmt = stmt.where(AuditEventRow.action == action)
    if rule_id:
        stmt = stmt.where(AuditEventRow.rule_id == rule_id)
    if actor:
        stmt = stmt.where(AuditEventRow.actor == actor)
    if new_state:
        stmt = stmt.where(AuditEventRow.new_state == new_state)
    if date_from:
        stmt = stmt.where(AuditEventRow.timestamp >= date_from)
    if date_to:
        stmt = stmt.where(AuditEventRow.timestamp <= date_to)

    rows = list(session.scalars(stmt).all())
    if source_record:
        needle = source_record.strip().upper()
        rows = [
            r
            for r in rows
            if any(needle == str(s).upper() for s in (r.source_records or []))
        ]
    rows.sort(key=lambda r: (r.timestamp, r.audit_id))
    total = len(rows)
    return rows[offset : offset + limit], total


def audit_facets(session: Session, run_id: Optional[str] = None) -> Dict[str, List[str]]:
    """Distinct values available for the audit filters."""
    stmt = select(AuditEventRow.action, AuditEventRow.rule_id, AuditEventRow.actor)
    if run_id:
        stmt = stmt.where(AuditEventRow.run_id == run_id)
    actions, rules, actors = set(), set(), set()
    for action, rule_id, actor in session.execute(stmt).all():
        actions.add(action)
        if rule_id:
            rules.add(rule_id)
        if actor:
            actors.add(actor)
    return {
        "actions": sorted(actions),
        "rule_ids": sorted(rules),
        "actors": sorted(actors),
    }


def register_dataset(
    session: Session, dataset_id: str, mode: str, seed: int, manifest: Dict[str, Any]
) -> DatasetRow:
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        row = DatasetRow(
            dataset_id=dataset_id,
            mode=mode,
            seed=seed,
            created_at=datetime.now(timezone.utc),
            manifest=manifest,
        )
        session.add(row)
    else:
        row.mode = mode
        row.seed = seed
        row.manifest = manifest
        row.created_at = datetime.now(timezone.utc)
    session.commit()
    return row


#: What belongs on the exception desk. PARTIAL_MATCH is included deliberately:
#: money that has not landed is an operational problem even when the settlement
#: arithmetic is sound. Defined once so the list and its summary can never
#: disagree about what they are counting.
EXCEPTION_DESK_STATUSES = [
    ReconciliationStatus.EXCEPTION.value,
    ReconciliationStatus.UNRESOLVED.value,
    ReconciliationStatus.REVIEW_REQUIRED.value,
    ReconciliationStatus.DUPLICATE.value,
    ReconciliationStatus.PARTIAL_MATCH.value,
]


def exception_summary(session: Session, run_id: str) -> Dict[str, Any]:
    """Aggregates for the exception page, computed from stored records."""
    rows, _ = query_records(
        session,
        run_id,
        statuses=EXCEPTION_DESK_STATUSES,
        limit=100_000,
    )
    by_reason: Dict[str, Dict[str, int]] = {}
    for row in rows:
        for code in row.reason_codes or []:
            bucket = by_reason.setdefault(code, {"count": 0, "value_paisa": 0})
            bucket["count"] += 1
            bucket["value_paisa"] += exposure_paisa(row)
    return {
        "total": len(rows),
        "total_value_paisa": sum(exposure_paisa(r) for r in rows),
        "unexplained_value_paisa": sum(abs(r.unexplained_value_paisa) for r in rows),
        "by_reason_code": dict(
            sorted(by_reason.items(), key=lambda kv: -kv[1]["value_paisa"])
        ),
    }
