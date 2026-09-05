"""Reconciliation record, exception and explanation endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import record_detail_dict, record_summary_dict, require_run_id
from app.core.money import format_inr
from app.db.session import get_session
from app.models.entities import ReconciliationRecord
from app.repositories import reconciliation_repo as repo
from app.schemas.api import (
    ExceptionListResponse,
    ExplainResponse,
    RecordDetail,
    RecordListResponse,
)
from app.services.ai.copilot import explain_record

router = APIRouter()

#: The exception desk status set lives in the repository so the list and its
#: summary are guaranteed to count the same thing.
EXCEPTION_STATUSES = repo.EXCEPTION_DESK_STATUSES

#: Plain-language headline per reason code. These describe what was OBSERVED,
#: never a suggested fix, because the engine does not invent resolutions.
REASON_HEADLINES: Dict[str, str] = {
    "UNKNOWN_BANK_CREDIT": "Unknown bank credit",
    "MISSING_SETTLEMENT": "Payment captured, never settled",
    "MISSING_BANK_TRANSACTION": "Settlement issued, cash not received",
    "DUPLICATE_SETTLEMENT": "Payment settled twice",
    "DUPLICATE_BANK_TRANSACTION": "Payout credited twice",
    "TDS_MISMATCH": "TDS withheld does not match the configured rate",
    "GST_MISMATCH": "GST on gateway fee does not match the statutory rate",
    "GATEWAY_FEE_MISMATCH": "Gateway fee does not match the contracted rate",
    "CHARGEBACK": "Settled payout reversed by chargeback",
    "NET_AMOUNT_VARIANCE": "Net settlement does not reconcile",
    "INVOICE_LINK_BROKEN": "No invoice found for this order",
    "BANK_AMOUNT_VARIANCE": "Bank credit differs from the payout amount",
}

#: What we could NOT establish, per reason code. This is the honest list the
#: exception desk shows instead of a fabricated resolution.
REASON_FINDINGS: Dict[str, List[str]] = {
    "UNKNOWN_BANK_CREDIT": [
        "No matching order",
        "No matching settlement",
        "No matching invoice",
    ],
    "MISSING_SETTLEMENT": [
        "No settlement record covers this payment",
        "No bank credit located",
    ],
    "MISSING_BANK_TRANSACTION": [
        "Settlement arithmetic verified",
        "No bank credit located for this payout",
    ],
    "DUPLICATE_SETTLEMENT": [
        "Two settlements claim the full order gross",
        "Only one payout is contractually due",
    ],
    "DUPLICATE_BANK_TRANSACTION": [
        "Two credits carry the same settlement reference and amount",
    ],
    "CHARGEBACK": [
        "Payout was settled and credited",
        "A later bank debit reverses it",
    ],
}


@router.get(
    "/reconciliation/records",
    response_model=RecordListResponse,
    tags=["reconciliation"],
)
def list_records(
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    match_type: Optional[str] = None,
    reason_code: Optional[str] = None,
    search: Optional[str] = None,
    min_variance_paisa: Optional[int] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> RecordListResponse:
    resolved = require_run_id(session, run_id)
    rows, total = repo.query_records(
        session,
        resolved,
        status=status,
        match_type=match_type,
        reason_code=reason_code,
        search=search,
        min_variance_paisa=min_variance_paisa,
        limit=limit,
        offset=offset,
    )
    return RecordListResponse(
        records=[record_summary_dict(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        run_id=resolved,
    )


@router.get(
    "/reconciliation/records/{reconciliation_id}",
    response_model=RecordDetail,
    tags=["reconciliation"],
)
def get_record(
    reconciliation_id: str,
    run_id: Optional[str] = None,
    session: Session = Depends(get_session),
) -> RecordDetail:
    record = repo.get_record(session, reconciliation_id, run_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"record {reconciliation_id} not found"
        )
    return RecordDetail(**record_detail_dict(record))


@router.get(
    "/reconciliation/records/{reconciliation_id}/explain",
    response_model=ExplainResponse,
    tags=["reconciliation"],
)
def explain(
    reconciliation_id: str,
    run_id: Optional[str] = None,
    session: Session = Depends(get_session),
) -> ExplainResponse:
    """Answer 'why was this matched?' strictly from recorded evidence."""
    payload = explain_record(session, reconciliation_id, run_id)
    if payload is None:
        raise HTTPException(
            status_code=404, detail=f"record {reconciliation_id} not found"
        )
    return ExplainResponse(**payload)


@router.get("/exceptions", response_model=ExceptionListResponse, tags=["exceptions"])
def list_exceptions(
    run_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> ExceptionListResponse:
    """The honest exception list. No fabricated resolutions, ever."""
    resolved = require_run_id(session, run_id)
    statuses = [status] if status else EXCEPTION_STATUSES
    rows, total = repo.query_records(
        session,
        resolved,
        statuses=statuses,
        reason_code=reason_code,
        order_by="exposure_desc",
        limit=limit,
        offset=offset,
    )
    items = [_to_exception_item(r) for r in rows]
    return ExceptionListResponse(
        exceptions=items,
        total=total,
        limit=limit,
        offset=offset,
        run_id=resolved,
        summary=repo.exception_summary(session, resolved),
    )


def _to_exception_item(record: ReconciliationRecord) -> Dict[str, Any]:
    payload = record_summary_dict(record)
    codes = record.reason_codes or []
    primary = next((c for c in codes if c in REASON_HEADLINES), None)
    payload["headline"] = (
        REASON_HEADLINES.get(primary, "Requires review")
        if primary
        else "Requires review"
    )

    findings: List[str] = []
    for code in codes:
        findings.extend(REASON_FINDINGS.get(code, []))
    if not findings:
        findings = [f"Reason code: {c}" for c in codes] or [
            "No deterministic explanation established"
        ]

    exposure = repo.exposure_paisa(record)
    payload["exposure_paisa"] = exposure
    if record.status == "PARTIAL_MATCH":
        findings.append(f"Cash awaited {format_inr(exposure)}")
    elif exposure:
        findings.append(f"Unexplained value {format_inr(exposure)}")

    payload["findings"] = findings
    payload["resolution_status"] = "HUMAN REVIEW REQUIRED"
    return payload
