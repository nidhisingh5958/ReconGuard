"""Deterministic candidate retrieval for residuals.

Before anything reasons about a residual, this module assembles the plausible
counterparts from the *other* residuals in the same run. The retrieval is
ordinary arithmetic over amounts and dates: no model is involved, and the
result is reproducible.

The pairing that matters in practice: an unidentified bank credit and an order
whose settlement is missing are frequently the same transaction with a broken
reference. The engine will not join them, because it refuses to guess. But it
can legitimately place them side by side, quantify how far apart they are, and
hand that to a human or an arbitrator to decide.

That division is the whole design. Retrieval is deterministic; only the
judgement is delegated, and the judgement is verified afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

RULE_CANDIDATE_AMOUNT = "RULE-ARB-001"
RULE_CANDIDATE_DATE = "RULE-ARB-002"
RULE_CANDIDATE_UNIQUE = "RULE-ARB-003"

#: Residuals that represent cash arriving with no home.
CREDIT_SIDE_CODES = frozenset({"UNKNOWN_BANK_CREDIT", "UNRECOGNISED_REFERENCE_FORMAT"})

#: Residuals that represent money owed with no cash located.
RECEIVABLE_SIDE_CODES = frozenset(
    {"MISSING_SETTLEMENT", "MISSING_BANK_TRANSACTION"}
)

MAX_CANDIDATES = 5


@dataclass(slots=True)
class ResidualCandidate:
    """A possible counterpart, with the distance to it measured."""

    candidate_id: str
    kind: str
    amount_paisa: int
    value_date: Optional[str]
    counterparty: Optional[str]
    source_records: List[str] = field(default_factory=list)
    amount_delta_paisa: int = 0
    date_delta_days: Optional[int] = None
    basis: List[str] = field(default_factory=list)

    @property
    def amount_matches_exactly(self) -> bool:
        return self.amount_delta_paisa == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "amount_paisa": self.amount_paisa,
            "value_date": self.value_date,
            "counterparty": self.counterparty,
            "source_records": self.source_records,
            "amount_delta_paisa": self.amount_delta_paisa,
            "date_delta_days": self.date_delta_days,
            "amount_matches_exactly": self.amount_matches_exactly,
            "basis": self.basis,
        }


@dataclass(slots=True)
class ResidualView:
    """The minimum a residual must expose to take part in candidate search.

    Deliberately structural rather than tied to the ORM row or the domain
    dataclass, so the same retrieval works in a unit test and against the
    database.
    """

    reconciliation_id: str
    status: str
    reason_codes: List[str]
    expected_amount_paisa: int
    actual_amount_paisa: int
    variance_paisa: int
    exposure_paisa: int
    counterparty: Optional[str]
    value_date: Optional[str]
    source_records: List[str] = field(default_factory=list)

    @property
    def is_credit_side(self) -> bool:
        return any(c in CREDIT_SIDE_CODES for c in self.reason_codes)

    @property
    def is_receivable_side(self) -> bool:
        return any(c in RECEIVABLE_SIDE_CODES for c in self.reason_codes)


def _parse(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _day_delta(left: Optional[str], right: Optional[str]) -> Optional[int]:
    a, b = _parse(left), _parse(right)
    if a is None or b is None:
        return None
    return (a - b).days


def build_candidates(
    residual: ResidualView,
    population: Sequence[ResidualView],
    amount_tolerance_paisa: int = 0,
    date_window_days: int = 7,
) -> List[ResidualCandidate]:
    """Find counterparts for one residual among the others in the same run.

    ``amount_tolerance_paisa`` defaults to zero: an inexact amount is not a
    candidate unless a caller explicitly widens the search, because a
    near-miss on money is usually a different transaction rather than the same
    one rounded.
    """
    if residual.is_credit_side:
        pool = [r for r in population if r.is_receivable_side]
        kind = "UNMATCHED_RECEIVABLE"
    elif residual.is_receivable_side:
        pool = [r for r in population if r.is_credit_side]
        kind = "UNIDENTIFIED_CREDIT"
    else:
        return []

    target_amount = residual.exposure_paisa or abs(residual.variance_paisa)
    if target_amount <= 0:
        return []

    found: List[ResidualCandidate] = []
    for other in pool:
        if other.reconciliation_id == residual.reconciliation_id:
            continue
        other_amount = other.exposure_paisa or abs(other.variance_paisa)
        if other_amount <= 0:
            continue

        amount_delta = other_amount - target_amount
        if abs(amount_delta) > amount_tolerance_paisa:
            continue

        date_delta = _day_delta(other.value_date, residual.value_date)
        if date_delta is not None and abs(date_delta) > date_window_days:
            continue

        basis = []
        if amount_delta == 0:
            basis.append(
                f"amount matches exactly at {target_amount} paise "
                f"({RULE_CANDIDATE_AMOUNT})"
            )
        else:
            basis.append(
                f"amount differs by {amount_delta} paise ({RULE_CANDIDATE_AMOUNT})"
            )
        if date_delta is not None:
            basis.append(
                f"value date {date_delta:+d} days apart, window +/-"
                f"{date_window_days} ({RULE_CANDIDATE_DATE})"
            )
        else:
            basis.append("no comparable value date on one side")

        # Customer alias matching basis
        if residual.counterparty and other.counterparty:
            from app.services.ai.confidence import compute_string_similarity, compute_identifier_score
            similarity = compute_string_similarity(residual.counterparty, other.counterparty)
            if similarity >= 0.70:
                basis.append(f"customer alias similarity {int(similarity * 100)}%: '{residual.counterparty}' vs '{other.counterparty}'")

        found.append(
            ResidualCandidate(
                candidate_id=other.reconciliation_id,
                kind=kind,
                amount_paisa=other_amount,
                value_date=other.value_date,
                counterparty=other.counterparty,
                source_records=list(other.source_records),
                amount_delta_paisa=amount_delta,
                date_delta_days=date_delta,
                basis=basis,
            )
        )

    found.sort(
        key=lambda c: (
            abs(c.amount_delta_paisa),
            abs(c.date_delta_days) if c.date_delta_days is not None else 999,
            c.candidate_id,
        )
    )
    return found[:MAX_CANDIDATES]


def unique_exact_candidate(
    candidates: Sequence[ResidualCandidate],
) -> Optional[ResidualCandidate]:
    """Return the single exact-amount candidate, if there is exactly one.

    Ambiguity is never broken by picking the closest date. Two credits of the
    same amount are genuinely indistinguishable on this evidence, and saying so
    is the correct answer.
    """
    exact = [c for c in candidates if c.amount_matches_exactly]
    return exact[0] if len(exact) == 1 else None
