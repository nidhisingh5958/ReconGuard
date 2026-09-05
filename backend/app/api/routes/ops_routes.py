"""Audit, metrics, rules, cash position and arbitration-queue endpoints."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import audit_event_dict, record_summary_dict, require_run_id, run_to_dict
from app.core.config import get_settings
from app.db.session import get_session
from app.models.entities import ReconciliationRecord
from app.repositories import reconciliation_repo as repo
from app.schemas.api import (
    ArbitrationQueueResponse,
    AuditListResponse,
    CashPositionResponse,
    MetricsResponse,
    RunSummary,
)
from app.services.ai.interfaces import build_residual_case, get_arbitrator
from app.services.forecasting.interfaces import (
    CashPosition,
    CashPositionLine,
    NoForecaster,
)

router = APIRouter()

METRIC_FORMULAS = {
    "match_rate": "deterministic_matches / records_processed",
    "exception_rate": "(exceptions + unresolved) / records_processed",
    "throughput": "records_processed / processing_time_seconds",
    "residuals": "review_required + exceptions + duplicates + unresolved",
    "net_settlement": "gross - gateway_fee - gst - tds - netted_refunds + adjustments",
    "gateway_fee": "gross x gateway_fee_bps / 10000",
    "gst_on_fee": "gateway_fee x gst_on_fee_bps / 10000",
    "tds": "gross x tds_bps / 10000",
}


@router.get("/audit", response_model=AuditListResponse, tags=["audit"])
def list_audit_events(
    run_id: Optional[str] = None,
    reconciliation_id: Optional[str] = None,
    action: Optional[str] = None,
    rule_id: Optional[str] = None,
    actor: Optional[str] = None,
    new_state: Optional[str] = None,
    source_record: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> AuditListResponse:
    resolved = require_run_id(session, run_id)
    events, total = repo.query_audit_events(
        session,
        run_id=resolved,
        reconciliation_id=reconciliation_id,
        action=action,
        rule_id=rule_id,
        actor=actor,
        new_state=new_state,
        source_record=source_record,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AuditListResponse(
        events=[audit_event_dict(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
        run_id=resolved,
        facets=repo.audit_facets(session, resolved),
    )


@router.get("/metrics", response_model=MetricsResponse, tags=["metrics"])
def get_metrics(
    run_id: Optional[str] = None, session: Session = Depends(get_session)
) -> MetricsResponse:
    """All figures derived from stored records of an actual run."""
    resolved = repo.resolve_run_id(session, run_id)
    if resolved is None:
        return MetricsResponse(formulas=METRIC_FORMULAS)

    run = repo.get_run(session, resolved)
    rows = list(
        session.scalars(
            select(ReconciliationRecord).where(
                ReconciliationRecord.run_id == resolved
            )
        ).all()
    )

    match_types = Counter(r.match_type for r in rows)
    confidence_bands: Counter = Counter()
    for r in rows:
        if r.confidence >= 1.0:
            confidence_bands["1.00 (proved)"] += 1
        elif r.confidence >= 0.95:
            confidence_bands["0.95-0.99"] += 1
        elif r.confidence >= 0.90:
            confidence_bands["0.90-0.94"] += 1
        elif r.confidence > 0:
            confidence_bands["below 0.90"] += 1
        else:
            confidence_bands["not established"] += 1

    daily: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"matched": 0, "residual": 0, "value_paisa": 0}
    )
    for r in rows:
        if r.value_date is None:
            continue
        bucket = daily[r.value_date.isoformat()]
        if r.status == "MATCHED":
            bucket["matched"] += 1
        else:
            bucket["residual"] += 1
        bucket["value_paisa"] += r.actual_amount_paisa

    daily_volume = [
        {"date": day, **counts} for day, counts in sorted(daily.items())
    ]

    top_exceptions = sorted(
        (r for r in rows if r.status != "MATCHED"),
        key=lambda r: -abs(r.unexplained_value_paisa),
    )[:10]

    recent = repo.list_runs(session, limit=10)

    return MetricsResponse(
        run=RunSummary(**run_to_dict(run)) if run else None,
        status_distribution=(run.status_distribution or {}) if run else {},
        reason_code_distribution=(run.reason_code_distribution or {}) if run else {},
        match_type_distribution=dict(match_types.most_common()),
        confidence_distribution=dict(confidence_bands),
        daily_volume=daily_volume,
        top_exceptions_by_value=[record_summary_dict(r) for r in top_exceptions],
        recent_runs=[RunSummary(**run_to_dict(r)) for r in recent],
        formulas=METRIC_FORMULAS,
    )


@router.get("/cash-position", response_model=CashPositionResponse, tags=["cash"])
def cash_position(
    run_id: Optional[str] = None, session: Session = Depends(get_session)
) -> CashPositionResponse:
    """Committed cash position derived from reconciled records only.

    Confirmed cash, committed inflows and at-risk value are facts read off the
    reconciliation. No prediction is included, and the response says so.
    """
    resolved = repo.resolve_run_id(session, run_id)
    if resolved is None:
        return CashPositionResponse(note="no runs yet")

    rows = list(
        session.scalars(
            select(ReconciliationRecord).where(
                ReconciliationRecord.run_id == resolved
            )
        ).all()
    )

    position = CashPosition(as_of=datetime.now(timezone.utc).date().isoformat())
    for r in rows:
        if r.status == "MATCHED":
            position.confirmed_received_paisa += r.actual_amount_paisa
        elif r.status == "PARTIAL_MATCH":
            position.committed_inflow_paisa += r.expected_amount_paisa
        elif r.status in ("DUPLICATE", "REVIEW_REQUIRED"):
            position.at_risk_paisa += abs(r.unexplained_value_paisa)
        else:
            position.unexplained_paisa += abs(r.unexplained_value_paisa)

    pending = [r for r in rows if r.status == "PARTIAL_MATCH"]
    for r in sorted(pending, key=lambda r: -r.expected_amount_paisa)[:25]:
        position.lines.append(
            CashPositionLine(
                value_date=r.value_date.isoformat() if r.value_date else None,
                label=f"Settlement due for {r.order_id}",
                amount_paisa=r.expected_amount_paisa,
                basis="settlement proved, bank credit not located",
                source_records=r.settlement_ids or [],
            )
        )

    return CashPositionResponse(
        run_id=resolved,
        confirmed_received_paisa=position.confirmed_received_paisa,
        committed_inflow_paisa=position.committed_inflow_paisa,
        at_risk_paisa=position.at_risk_paisa,
        unexplained_paisa=position.unexplained_paisa,
        lines=[line.to_dict() for line in position.lines],
        basis="deterministic",
        includes_prediction=False,
        forecast=NoForecaster().forecast(horizon_days=30, history=rows),
        note=(
            "Committed position only. Predictive forecasting is a next-phase "
            "component and is deliberately absent rather than approximated."
        ),
    )


@router.get(
    "/arbitration/queue",
    response_model=ArbitrationQueueResponse,
    tags=["ai"],
)
def arbitration_queue(
    run_id: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> ArbitrationQueueResponse:
    """Exactly what a future arbitrator would receive: residuals, nothing else."""
    settings = get_settings()
    resolved = require_run_id(session, run_id)
    rows, _ = repo.query_records(
        session,
        resolved,
        statuses=["EXCEPTION", "UNRESOLVED", "REVIEW_REQUIRED", "DUPLICATE"],
        limit=limit,
    )
    arbitrator = get_arbitrator(settings.ai_provider)
    residuals = [
        {
            "residual_id": r.reconciliation_id,
            "status": r.status,
            "reason_codes": r.reason_codes or [],
            "expected_amount_paisa": r.expected_amount_paisa,
            "actual_amount_paisa": r.actual_amount_paisa,
            "variance_paisa": r.variance_paisa,
            "counterparty": r.counterparty,
            "value_date": r.value_date.isoformat() if r.value_date else None,
            "source_records": r.source_records or [],
            "evidence_count": len(r.evidence or []),
        }
        for r in rows
    ]
    return ArbitrationQueueResponse(
        run_id=resolved,
        arbitrator=arbitrator.name,
        ai_enabled=settings.ai_enabled,
        queue_size=len(residuals),
        residuals=residuals,
        note=(
            "The arbitrator receives only these residual cases, never the full "
            "dataset. With no provider configured the NullArbitrator declines "
            "every case and the residuals stay on the human review desk."
        ),
    )
