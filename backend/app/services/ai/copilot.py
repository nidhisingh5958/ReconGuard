"""Evidence-grounded Q&A foundation.

This is the retrieval half of the finance copilot, and it is deliberately the
half that ships first. Given a reconciliation id it assembles the complete,
already-proved explanation: the accounting derivation, the source records, the
matching logic and the audit events.

There is no language model here and the answer is not generated. It is read
back from what the engine proved at run time. When the copilot does gain a
language layer, this function is what it will be constrained to speak from, so
the model can phrase an explanation but cannot invent one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.money import format_inr
from app.models.entities import ReconciliationRecord
from app.repositories import reconciliation_repo as repo


def explain_record(
    session: Session, reconciliation_id: str, run_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Answer 'why was this matched?' entirely from stored evidence."""
    record = repo.get_record(session, reconciliation_id, run_id)
    if record is None:
        return None

    events, _ = repo.query_audit_events(
        session, run_id=record.run_id, reconciliation_id=reconciliation_id, limit=500
    )

    return {
        "reconciliation_id": record.reconciliation_id,
        "run_id": record.run_id,
        "question": "Why was this transaction classified this way?",
        "verdict": _verdict_sentence(record),
        "status": record.status,
        "match_type": record.match_type,
        "confidence": record.confidence,
        "confidence_method": record.confidence_method,
        "financial_calculation": record.calculation,
        "source_records": record.source_records,
        "matching_logic": _matching_logic(record),
        "evidence": record.evidence,
        "adjustments": record.adjustments,
        "reason_codes": record.reason_codes,
        "rules_applied": record.rule_ids,
        "audit_events": [
            {
                "audit_id": e.audit_id,
                "timestamp": e.timestamp.isoformat(),
                "action": e.action,
                "actor": e.actor,
                "rule_id": e.rule_id,
                "calculation": e.calculation,
                "previous_state": e.previous_state,
                "new_state": e.new_state,
            }
            for e in events
        ],
        "grounded": True,
        "generated_by": "deterministic-retrieval",
    }


def _verdict_sentence(record: ReconciliationRecord) -> str:
    """A plain-language summary assembled only from stored numbers."""
    variance = record.variance_paisa
    if record.status == "MATCHED" and variance == 0:
        return (
            f"Matched by {record.match_type} at confidence {record.confidence:.2f} "
            f"({record.confidence_method}). The settlement equation closed exactly "
            f"at {format_inr(record.actual_amount_paisa)}."
        )
    if record.status == "MATCHED":
        return (
            f"Matched by {record.match_type} at confidence {record.confidence:.2f}. "
            f"Residual difference of {format_inr(abs(variance))} was absorbed by an "
            f"explicit tolerance rule, not ignored."
        )
    if record.status == "PARTIAL_MATCH":
        return (
            f"The settlement side is proved, but the cash has not been located on "
            f"the bank statement. {format_inr(record.expected_amount_paisa)} is "
            f"expected and not yet confirmed as received."
        )
    if record.status == "DUPLICATE":
        return (
            f"The same payout appears more than once. Exposure is "
            f"{format_inr(abs(variance))} above the single expected payout of "
            f"{format_inr(record.expected_amount_paisa)}."
        )
    if record.status == "REVIEW_REQUIRED":
        return (
            f"A discrepancy of {format_inr(abs(variance))} was quantified and "
            f"attributed to {', '.join(record.reason_codes) or 'an identified cause'}. "
            f"The engine does not guess the correction; a human decides."
        )
    return (
        f"No counterpart could be proved. {format_inr(abs(variance))} is unexplained "
        f"and is reported as an exception rather than resolved by inference."
    )


def _matching_logic(record: ReconciliationRecord) -> List[Dict[str, str]]:
    """The ordered chain of deterministic steps that produced this result."""
    steps: List[Dict[str, str]] = []
    if record.payment_id:
        steps.append(
            {
                "layer": "Layer 1 - exact identifiers",
                "detail": (
                    f"Order {record.order_id} resolved to payment {record.payment_id}"
                    + (
                        f", settlements {', '.join(record.settlement_ids)}"
                        if record.settlement_ids
                        else ", no settlement found"
                    )
                ),
            }
        )
    steps.append(
        {
            "layer": "Layer 2 - accounting invariant",
            "detail": (
                f"Expected net {format_inr(record.expected_amount_paisa)} vs actual "
                f"{format_inr(record.actual_amount_paisa)}, variance "
                f"{format_inr(record.variance_paisa)}"
            ),
        }
    )
    if record.match_type in ("AGGREGATED_SETTLEMENT", "SPLIT_SETTLEMENT"):
        steps.append(
            {
                "layer": "Layer 4 - N:M matching",
                "detail": (
                    f"Relationship resolved as {record.match_type} across "
                    f"{len(record.settlement_ids)} settlement record(s)"
                ),
            }
        )
    if record.adjustments:
        steps.append(
            {
                "layer": "Layer 5 - netting",
                "detail": (
                    f"{len(record.adjustments)} adjustment(s) attributed: "
                    + ", ".join(a.get("type", "") for a in record.adjustments)
                ),
            }
        )
    if record.bank_transaction_ids:
        steps.append(
            {
                "layer": "Layers 1/3 - bank confirmation",
                "detail": (
                    f"Cash confirmed by {', '.join(record.bank_transaction_ids)} via "
                    f"{record.confidence_method}"
                ),
            }
        )
    else:
        steps.append(
            {
                "layer": "Layers 1/3 - bank confirmation",
                "detail": "No bank credit could be linked to this payout",
            }
        )
    return steps
