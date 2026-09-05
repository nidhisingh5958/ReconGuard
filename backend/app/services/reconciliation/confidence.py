"""Confidence model.

Confidence here is NOT a probability and is never sampled, learned or guessed.
Each value is a fixed constant attached to a named deterministic rule, and the
rule that produced it is stored alongside it. If you cannot name the rule, you
do not get to emit a number.

    1.00  an exact identifier matched, or an accounting invariant closed to the
          paisa. There is nothing probabilistic left to express.
    0.99  the invariant closed inside the configured rounding tolerance.
    0.95  a truncated bank reference resolved to exactly one settlement once
          the payout amount was also required to agree.
    0.90  no usable reference; matched on exact amount, inside the date window,
          against a narration that identifies the gateway as counterparty.
    0.00  not established.

A composite result takes the MINIMUM of its constituent confidences, not the
product and not an average: a chain of evidence is exactly as strong as its
weakest verified link, and multiplying independent-looking factors would invent
precision that the underlying rules do not have.
"""

from __future__ import annotations

from typing import Iterable, Tuple

from app.domain.enums import ConfidenceMethod

EXACT_IDENTIFIER = 1.0
ACCOUNTING_INVARIANT = 1.0
ROUNDING_TOLERANCE = 0.99
REFERENCE_PREFIX_UNIQUE = 0.95
AMOUNT_DATE_COMPOSITE = 0.90
NOT_ESTABLISHED = 0.0

#: The single source of truth mapping a method to its fixed confidence value.
METHOD_CONFIDENCE = {
    ConfidenceMethod.EXACT_IDENTIFIER: EXACT_IDENTIFIER,
    ConfidenceMethod.ACCOUNTING_INVARIANT: ACCOUNTING_INVARIANT,
    ConfidenceMethod.AGGREGATED_INVARIANT: ACCOUNTING_INVARIANT,
    ConfidenceMethod.REFERENCE_EXTRACTION_EXACT: EXACT_IDENTIFIER,
    ConfidenceMethod.ACCOUNTING_INVARIANT_WITHIN_ROUNDING_TOLERANCE: ROUNDING_TOLERANCE,
    ConfidenceMethod.REFERENCE_PREFIX_UNIQUE: REFERENCE_PREFIX_UNIQUE,
    ConfidenceMethod.AMOUNT_DATE_COUNTERPARTY_COMPOSITE: AMOUNT_DATE_COMPOSITE,
    ConfidenceMethod.NOT_ESTABLISHED: NOT_ESTABLISHED,
}


def confidence_for(method: ConfidenceMethod) -> float:
    """Look up the fixed confidence for a named method."""
    return METHOD_CONFIDENCE[method]


def weakest_link(
    methods: Iterable[ConfidenceMethod],
) -> Tuple[float, ConfidenceMethod]:
    """Combine evidence by taking the weakest verified link.

    Returns ``(confidence, method)`` where the method names the link that set
    the ceiling, so the UI can say which step limited the confidence.
    """
    chosen_method = ConfidenceMethod.NOT_ESTABLISHED
    chosen_value = NOT_ESTABLISHED
    first = True
    for method in methods:
        value = confidence_for(method)
        if first or value < chosen_value:
            chosen_value = value
            chosen_method = method
            first = False
    return chosen_value, chosen_method
