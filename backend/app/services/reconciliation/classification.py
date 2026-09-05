"""Status classification.

The single rule governing this module: a result is only MATCHED when the money
is fully explained. Everything else keeps a status that tells an operator what
kind of work it needs, and carries at least one reason code saying why.

    MATCHED          settlement proved by an accounting invariant AND the bank
                     credit located. Nothing outstanding.
    PARTIAL_MATCH    the settlement side is proved but the cash has not landed,
                     or has not been located on the statement.
    REVIEW_REQUIRED  a real, quantified discrepancy attributed to a specific
                     component. A human decides; the engine does not guess.
    DUPLICATE        the same payout appears more than once. Exposure is the
                     duplicated amount, not zero.
    EXCEPTION        no counterpart exists at all. Honest dead end.
    UNRESOLVED       reached the end of the deterministic layers without an
                     explanation. This is the ONLY status handed to the future
                     arbitrator, and it is deliberately rare.

There is no path through this function that produces MATCHED without a proved
invariant, and no path that produces any residual status without a reason code.
"""

from __future__ import annotations

from typing import List, Sequence

from app.domain.enums import ReasonCode, ReconciliationStatus

#: Reason codes that describe how a match was achieved rather than a problem.
#: Their presence never blocks a MATCHED status.
INFORMATIONAL_REASON_CODES = frozenset(
    {
        ReasonCode.ROUNDING_TOLERANCE_APPLIED,
        ReasonCode.AGGREGATED_SETTLEMENT,
        ReasonCode.SPLIT_SETTLEMENT,
        ReasonCode.REFUND_NETTED,
        ReasonCode.PARTIAL_REFUND,
        ReasonCode.DELAYED_SETTLEMENT,
        ReasonCode.TRUNCATED_BANK_REFERENCE,
        ReasonCode.BANK_REFERENCE_NORMALIZED,
        ReasonCode.PROMOTED_RULE_APPLIED,
        ReasonCode.COUNTERPARTY_ALIAS_RESOLVED,
        ReasonCode.DATE_FORMAT_NORMALIZED,
        ReasonCode.INVOICE_TYPO_RESOLVED,
    }
)

#: Reason codes that force human review regardless of anything else.
BLOCKING_REASON_CODES = frozenset(
    {
        ReasonCode.NET_AMOUNT_VARIANCE,
        ReasonCode.GATEWAY_FEE_MISMATCH,
        ReasonCode.GST_MISMATCH,
        ReasonCode.TDS_MISMATCH,
        ReasonCode.CHARGEBACK,
        ReasonCode.BANK_AMOUNT_VARIANCE,
        ReasonCode.INVOICE_LINK_BROKEN,
    }
)


def classify(
    has_settlement: bool,
    invariant_proved: bool,
    bank_found: bool,
    has_duplicates: bool,
    reason_codes: Sequence[ReasonCode],
) -> ReconciliationStatus:
    """Decide the final status from proved facts only."""
    codes = set(reason_codes)

    if not has_settlement:
        return ReconciliationStatus.EXCEPTION

    if has_duplicates or ReasonCode.DUPLICATE_SETTLEMENT in codes:
        return ReconciliationStatus.DUPLICATE

    if ReasonCode.DUPLICATE_BANK_TRANSACTION in codes:
        return ReconciliationStatus.DUPLICATE

    if codes & BLOCKING_REASON_CODES:
        return ReconciliationStatus.REVIEW_REQUIRED

    if not invariant_proved:
        # An unproved invariant with no attributed cause is the one case the
        # deterministic engine genuinely cannot explain.
        return ReconciliationStatus.UNRESOLVED

    if not bank_found:
        return ReconciliationStatus.PARTIAL_MATCH

    return ReconciliationStatus.MATCHED


def dedupe_reason_codes(codes: Sequence[ReasonCode]) -> List[ReasonCode]:
    """Stable de-duplication, preserving the order the engine discovered them."""
    seen = set()
    ordered: List[ReasonCode] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def requires_human_review(status: ReconciliationStatus) -> bool:
    return status in (
        ReconciliationStatus.REVIEW_REQUIRED,
        ReconciliationStatus.EXCEPTION,
        ReconciliationStatus.DUPLICATE,
        ReconciliationStatus.UNRESOLVED,
    )
