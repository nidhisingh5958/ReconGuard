"""The deterministic arbitrator.

This is the default arbitrator and it requires no model, no network and no API
key. It applies named, auditable rules to the residual and to the candidates
deterministic retrieval found.

Why an arbitrator that does not use AI is the right default, and not a
placeholder: most of what a residual needs is not judgement at all. A payout
that is proved but uncollected needs an accrual, not an opinion. A duplicate
receipt needs a liability recognised. An unidentified credit needs parking in
suspense. Those are bookkeeping policy, and applying policy deterministically
is strictly better than asking a model to reproduce it.

It reaches RESOLVE in exactly one situation: an unidentified credit and an
unmatched receivable that agree to the paisa, inside the date window, with no
other candidate competing. That is not a guess, it is a one-to-one pairing that
the base engine declined only because the bank reference was unusable.
Everything else is PROBABLE (a proposal with a booked correction) or UNRESOLVED.

It never returns a confidence it cannot name a rule for.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision
from app.services.accounting.journal import JournalBatch, JournalBuilder
from app.services.ai.candidates import unique_exact_candidate
from app.services.ai.interfaces import ResidualArbitrator, ResidualCase

RULE_ARB_EXACT_PAIR = "RULE-ARB-010"
RULE_ARB_ACCRUAL = "RULE-ARB-011"
RULE_ARB_SUSPENSE = "RULE-ARB-012"
RULE_ARB_DUPLICATE = "RULE-ARB-013"
RULE_ARB_CHARGEBACK = "RULE-ARB-014"
RULE_ARB_TAX = "RULE-ARB-015"
RULE_ARB_VARIANCE = "RULE-ARB-016"

#: Fixed confidences, each bound to the rule that earns it. Same discipline as
#: the matching engine: if you cannot name the rule, you do not get a number.
CONFIDENCE_EXACT_PAIR = 0.95
CONFIDENCE_POLICY_BOOKING = 0.80
CONFIDENCE_ATTRIBUTED_VARIANCE = 0.75

#: reason code -> (action, rule id, confidence, human-readable policy)
POLICY_BY_REASON: Dict[str, Tuple[str, str, float, str]] = {
    "MISSING_SETTLEMENT": (
        "ACCRUE_SETTLEMENT_RECEIVABLE",
        RULE_ARB_ACCRUAL,
        CONFIDENCE_POLICY_BOOKING,
        "Payment captured but never settled: accrue the payout as receivable "
        "from the gateway.",
    ),
    "MISSING_BANK_TRANSACTION": (
        "ACCRUE_SETTLEMENT_RECEIVABLE",
        RULE_ARB_ACCRUAL,
        CONFIDENCE_POLICY_BOOKING,
        "Settlement proved but cash not located: accrue the payout as "
        "receivable pending the credit.",
    ),
    "UNKNOWN_BANK_CREDIT": (
        "PARK_UNIDENTIFIED_CREDIT",
        RULE_ARB_SUSPENSE,
        CONFIDENCE_POLICY_BOOKING,
        "Cash received with no attributable order: park it in suspense rather "
        "than recognising revenue against an unknown counterparty.",
    ),
    "DUPLICATE_SETTLEMENT": (
        "RECOGNISE_DUPLICATE_LIABILITY",
        RULE_ARB_DUPLICATE,
        CONFIDENCE_POLICY_BOOKING,
        "The same payout was received twice: recognise the excess as "
        "potentially repayable.",
    ),
    "DUPLICATE_BANK_TRANSACTION": (
        "RECOGNISE_DUPLICATE_LIABILITY",
        RULE_ARB_DUPLICATE,
        CONFIDENCE_POLICY_BOOKING,
        "The same payout was credited twice: recognise the excess as "
        "potentially repayable.",
    ),
    "CHARGEBACK": (
        "BOOK_CHARGEBACK_LOSS",
        RULE_ARB_CHARGEBACK,
        CONFIDENCE_POLICY_BOOKING,
        "A settled payout was reversed: book the loss against the bank.",
    ),
    "TDS_MISMATCH": (
        "BOOK_TDS_DIFFERENCE",
        RULE_ARB_TAX,
        CONFIDENCE_ATTRIBUTED_VARIANCE,
        "Tax withheld exceeds the configured rate: book the difference as "
        "recoverable TDS pending confirmation.",
    ),
    "GST_MISMATCH": (
        "BOOK_GST_DIFFERENCE",
        RULE_ARB_TAX,
        CONFIDENCE_ATTRIBUTED_VARIANCE,
        "GST on the gateway fee differs from the statutory rate: book the "
        "difference against input credit.",
    ),
    "GATEWAY_FEE_MISMATCH": (
        "BOOK_FEE_DIFFERENCE",
        RULE_ARB_TAX,
        CONFIDENCE_ATTRIBUTED_VARIANCE,
        "Gateway fee differs from the contracted rate: book the difference to "
        "fee expense.",
    ),
    "NET_AMOUNT_VARIANCE": (
        "BOOK_VARIANCE",
        RULE_ARB_VARIANCE,
        CONFIDENCE_ATTRIBUTED_VARIANCE,
        "The settlement equation did not close: book the attributed variance "
        "pending a human decision.",
    ),
}

#: Order matters: the most specific attribution wins when several codes are set.
REASON_PRIORITY = (
    "UNKNOWN_BANK_CREDIT",
    "MISSING_SETTLEMENT",
    "DUPLICATE_SETTLEMENT",
    "DUPLICATE_BANK_TRANSACTION",
    "CHARGEBACK",
    "TDS_MISMATCH",
    "GST_MISMATCH",
    "GATEWAY_FEE_MISMATCH",
    "MISSING_BANK_TRANSACTION",
    "NET_AMOUNT_VARIANCE",
)


class DeterministicArbitrator(ResidualArbitrator):
    """Rule-based arbitration. No model, no network, fully reproducible."""

    name = "deterministic"
    uses_model = False

    def __init__(self, date_window_days: int = 7) -> None:
        self.date_window_days = date_window_days
        self._journal = JournalBuilder()

    # -- public ------------------------------------------------------------
    def resolve(self, residual: ResidualCase) -> ArbitrationResult:
        result, _ = self.resolve_with_journal(residual)
        return result

    def resolve_with_journal(
        self, residual: ResidualCase
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        """Return the proposal and the journal batch backing it."""
        paired = self._try_exact_pair(residual)
        if paired is not None:
            return paired

        return self._apply_policy(residual)

    # -- internals ---------------------------------------------------------
    def _try_exact_pair(
        self, residual: ResidualCase
    ) -> Optional[Tuple[ArbitrationResult, Optional[JournalBatch]]]:
        """Pair an unidentified credit with an unmatched receivable.

        Requires a single candidate agreeing to the paisa. Two candidates of the
        same amount are genuinely indistinguishable on this evidence, and the
        correct answer there is to say so rather than to pick one.
        """
        candidate = unique_exact_candidate(residual.candidates)
        if candidate is None:
            return None
        if candidate.date_delta_days is not None and (
            abs(candidate.date_delta_days) > self.date_window_days
        ):
            return None

        amount = residual.exposure_paisa or abs(residual.variance_paisa)
        evidence = sorted(
            set(residual.source_records)
            | set(candidate.source_records)
            | {candidate.candidate_id}
        )
        reason = (
            f"Paired with {candidate.candidate_id}: both sides are for exactly "
            f"{amount} paise"
            + (
                f" and are {candidate.date_delta_days:+d} days apart"
                if candidate.date_delta_days is not None
                else ""
            )
            + f", and no other residual in this run matches that amount. The base "
            f"engine declined the link only because the bank reference was "
            f"unusable, not because the amounts disagree ({RULE_ARB_EXACT_PAIR})."
        )

        batch = self._journal.build(
            residual_id=residual.residual_id,
            action="ACCRUE_SETTLEMENT_RECEIVABLE",
            amount_paisa=amount,
            source_records=evidence,
            confidence=CONFIDENCE_EXACT_PAIR,
            value_date=_as_date(residual.value_date),
        )

        result = ArbitrationResult(
            residual_id=residual.residual_id,
            decision=ArbitrationDecision.RESOLVE,
            confidence=CONFIDENCE_EXACT_PAIR,
            reason=reason,
            evidence=evidence,
            proposed_action="ACCRUE_SETTLEMENT_RECEIVABLE",
            journal_entry=batch.entries[0] if batch and batch.entries else None,
            requires_human_review=True,
            arbitrator=self.name,
        )
        return result, batch

    def _apply_policy(
        self, residual: ResidualCase
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        code = self._primary_reason(residual.reason_codes)
        if code is None:
            return (
                ArbitrationResult(
                    residual_id=residual.residual_id,
                    decision=ArbitrationDecision.UNRESOLVED,
                    confidence=0.0,
                    reason=(
                        "No bookkeeping policy covers this combination of reason "
                        f"codes {residual.reason_codes}. Escalated for human "
                        "review rather than booked on a guess."
                    ),
                    evidence=list(residual.source_records),
                    requires_human_review=True,
                    arbitrator=self.name,
                ),
                None,
            )

        action, rule_id, confidence, policy = POLICY_BY_REASON[code]
        amount = residual.exposure_paisa or abs(residual.variance_paisa)
        if amount <= 0:
            return (
                ArbitrationResult(
                    residual_id=residual.residual_id,
                    decision=ArbitrationDecision.UNRESOLVED,
                    confidence=0.0,
                    reason=(
                        f"{code} carries no unexplained amount, so there is "
                        "nothing to book."
                    ),
                    evidence=list(residual.source_records),
                    requires_human_review=True,
                    arbitrator=self.name,
                ),
                None,
            )

        batch = self._journal.build(
            residual_id=residual.residual_id,
            action=action,
            amount_paisa=amount,
            source_records=residual.source_records,
            confidence=confidence,
            value_date=_as_date(residual.value_date),
        )

        near_misses = [c for c in residual.candidates if not c.amount_matches_exactly]
        ambiguity = ""
        if len(residual.candidates) > 1:
            ambiguity = (
                f" {len(residual.candidates)} candidate counterparts were found and "
                f"none is uniquely exact, so no pairing is asserted."
            )
        elif near_misses:
            ambiguity = (
                f" The nearest candidate {near_misses[0].candidate_id} differs by "
                f"{near_misses[0].amount_delta_paisa} paise, which is not a match."
            )

        result = ArbitrationResult(
            residual_id=residual.residual_id,
            decision=ArbitrationDecision.PROBABLE,
            confidence=confidence,
            reason=f"{policy} ({rule_id}).{ambiguity}",
            evidence=list(residual.source_records),
            proposed_action=action,
            journal_entry=batch.entries[0] if batch and batch.entries else None,
            requires_human_review=True,
            arbitrator=self.name,
        )
        return result, batch

    @staticmethod
    def _primary_reason(codes: List[str]) -> Optional[str]:
        for candidate in REASON_PRIORITY:
            if candidate in codes:
                return candidate
        return None


def _as_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
