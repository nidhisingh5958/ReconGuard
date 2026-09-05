"""Shared API dependencies and serialisation helpers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.entities import AuditEventRow, ReconciliationRecord, ReconciliationRun
from app.repositories import reconciliation_repo as repo

SessionDep = Depends(get_session)


def require_run_id(session: Session, run_id: Optional[str]) -> str:
    """Resolve an explicit run id, or fall back to the most recent run."""
    resolved = repo.resolve_run_id(session, run_id)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "no reconciliation runs exist yet. Start one with "
                "POST /api/reconciliation/run"
            ),
        )
    if repo.get_run(session, resolved) is None:
        raise HTTPException(status_code=404, detail=f"run {resolved} not found")
    return resolved


def run_to_dict(run: ReconciliationRun) -> Dict[str, Any]:
    return {
        "run_id": run.run_id,
        "label": run.label or "",
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "records_processed": run.records_processed,
        "total_source_records": run.total_source_records,
        "deterministic_matches": run.deterministic_matches,
        "partial_matches": run.partial_matches,
        "review_required": run.review_required,
        "exceptions": run.exceptions,
        "duplicates": run.duplicates,
        "unresolved": run.unresolved,
        "residuals": run.residuals,
        "processing_time_ms": run.processing_time_ms,
        "throughput_rps": run.throughput_rps,
        "match_rate": run.match_rate,
        "exception_rate": run.exception_rate,
        "total_reconciled_paisa": run.total_reconciled_paisa,
        "total_variance_paisa": run.total_variance_paisa,
        "unexplained_value_paisa": run.unexplained_value_paisa,
        "engine_version": run.engine_version,
        "dataset_id": run.dataset_id,
        "dataset_mode": run.dataset_mode,
        "status_distribution": run.status_distribution or {},
        "reason_code_distribution": run.reason_code_distribution or {},
        "accounting_config": run.accounting_config or {},
    }


def record_summary_dict(record: ReconciliationRecord) -> Dict[str, Any]:
    return {
        "reconciliation_id": record.reconciliation_id,
        "run_id": record.run_id,
        "status": record.status,
        "match_type": record.match_type,
        "confidence": record.confidence,
        "confidence_method": record.confidence_method,
        "order_id": record.order_id,
        "payment_id": record.payment_id,
        "invoice_id": record.invoice_id,
        "settlement_ids": record.settlement_ids or [],
        "bank_transaction_ids": record.bank_transaction_ids or [],
        "counterparty": record.counterparty,
        "gross_amount_paisa": record.gross_amount_paisa,
        "expected_amount_paisa": record.expected_amount_paisa,
        "actual_amount_paisa": record.actual_amount_paisa,
        "variance_paisa": record.variance_paisa,
        "unexplained_value_paisa": record.unexplained_value_paisa,
        "reason_codes": record.reason_codes or [],
        "rule_ids": record.rule_ids or [],
        "value_date": record.value_date,
        "evidence_count": len(record.evidence or []),
        "requires_human_review": bool(record.requires_human_review),
    }


def record_detail_dict(record: ReconciliationRecord) -> Dict[str, Any]:
    payload = record_summary_dict(record)
    payload.update(
        {
            "source_records": record.source_records or [],
            "calculation": record.calculation or [],
            "evidence": record.evidence or [],
            "adjustments": record.adjustments or [],
            "created_at": record.created_at,
        }
    )
    return payload


def audit_event_dict(event: AuditEventRow) -> Dict[str, Any]:
    return {
        "audit_id": event.audit_id,
        "run_id": event.run_id,
        "timestamp": event.timestamp,
        "action": event.action,
        "actor": event.actor,
        "reconciliation_id": event.reconciliation_id,
        "rule_id": event.rule_id,
        "calculation": event.calculation or "",
        "previous_state": event.previous_state,
        "new_state": event.new_state,
        "source_records": event.source_records or [],
        "evidence": event.evidence or [],
        "detail": event.detail or {},
        "system_version": event.system_version or "",
    }


PaginationLimit = Query(default=100, ge=1, le=1000)
PaginationOffset = Query(default=0, ge=0)
