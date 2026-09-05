"""Layers 1 and 3 on the bank side - linking a settlement to its bank credit.

Resolution is strictly ordered, strongest first, and stops at the first layer
that produces an answer:

1. Exact reference. The settlement key appears verbatim in the narration.
   Confidence 1.0, because the bank told us the settlement id.
2. Truncated reference. The narration carries a proper prefix of the key and
   the payout amount agrees, and the prefix resolves to exactly one settlement.
   Confidence 0.95, and the weaker basis is labelled on the result.
3. Amount and date window. No usable reference at all, but the credit is for
   the exact payout amount, lands inside the configured date window, and the
   narration identifies the gateway as counterparty. Confidence 0.90.

Each bank row can be claimed by at most one settlement. Settlements are
processed in sorted id order so that the assignment is reproducible rather than
dependent on dict iteration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from app.core.config import ReconciliationConfig
from app.domain.enums import ConfidenceMethod, MatchType, ReasonCode
from app.domain.reconciliation import Evidence
from app.domain.sources import SettlementRecord
from app.services.normalization.dates import days_between
from app.services.normalization.references import settlement_numeric_key
from app.services.reconciliation.indexes import (
    MIN_PREFIX_LENGTH,
    BankView,
    ReconciliationIndex,
)

RULE_BANK_EXACT_REFERENCE = "RULE-MATCH-001"
RULE_BANK_PREFIX_REFERENCE = "RULE-MATCH-002"
RULE_BANK_AMOUNT_DATE = "RULE-MATCH-003"


@dataclass
class BankMatch:
    """Outcome of linking one settlement to the bank statement."""

    views: List[BankView] = field(default_factory=list)
    match_type: MatchType = MatchType.NONE
    method: ConfidenceMethod = ConfidenceMethod.NOT_ESTABLISHED
    reason_codes: List[ReasonCode] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    rule_ids: List[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.views)

    @property
    def total_credit_paisa(self) -> int:
        return sum(v.record.credit_amount_paisa for v in self.views)

    @property
    def transaction_ids(self) -> List[str]:
        return [v.record.bank_transaction_id for v in self.views]


class BankMatcher:
    """Claims bank credits for settlements, strongest evidence first."""

    def __init__(
        self, index: ReconciliationIndex, config: ReconciliationConfig
    ) -> None:
        self.index = index
        self.config = config
        self.claimed: Set[str] = set()
        # The settlement-to-bank link is a property of the settlement, not of
        # the order asking about it. An aggregated payout is queried once per
        # covered payment, and without memoisation the second caller would find
        # the credit already claimed and wrongly report it missing.
        self._resolved: Dict[str, BankMatch] = {}

    def _unclaimed(self, views: List[BankView]) -> List[BankView]:
        return [
            v
            for v in views
            if v.is_credit and v.record.bank_transaction_id not in self.claimed
        ]

    def _claim(self, views: List[BankView]) -> None:
        for v in views:
            self.claimed.add(v.record.bank_transaction_id)

    def match(self, settlement: SettlementRecord) -> BankMatch:
        cached = self._resolved.get(settlement.settlement_id)
        if cached is not None:
            return cached
        result = self._match_uncached(settlement)
        self._resolved[settlement.settlement_id] = result
        return result

    def _match_uncached(self, settlement: SettlementRecord) -> BankMatch:
        key = settlement_numeric_key(settlement.settlement_id)
        if not key:
            return BankMatch(reason_codes=[ReasonCode.MISSING_BANK_TRANSACTION])

        # --- layer 1: exact reference ------------------------------------
        exact = self._unclaimed(self.index.credits_by_key.get(key, []))
        if exact:
            self._claim(exact)
            match = BankMatch(
                views=exact,
                match_type=MatchType.EXACT_BANK_REFERENCE,
                method=ConfidenceMethod.REFERENCE_EXTRACTION_EXACT,
                rule_ids=[RULE_BANK_EXACT_REFERENCE],
                evidence=[
                    Evidence(
                        source="BANK",
                        record_id=v.record.bank_transaction_id,
                        fact=(
                            f"Narration {v.record.description!r} contains settlement "
                            f"key {key}; credit {v.record.credit_amount_paisa} paise"
                        ),
                        amount_paisa=v.record.credit_amount_paisa,
                        detail={"rule_id": RULE_BANK_EXACT_REFERENCE},
                    )
                    for v in exact
                ],
            )
            self._annotate(match, settlement)
            return match

        # --- layer 2: truncated reference --------------------------------
        for length in range(len(key) - 1, MIN_PREFIX_LENGTH - 1, -1):
            prefix = key[:length]
            candidates = self._unclaimed(self.index.credits_by_key.get(prefix, []))
            if not candidates:
                continue
            resolved = self.index.resolve_prefix(prefix, settlement.net_amount_paisa)
            if resolved is None or resolved.settlement_id != settlement.settlement_id:
                continue
            confirmed = [
                v
                for v in candidates
                if v.record.credit_amount_paisa == settlement.net_amount_paisa
            ]
            if not confirmed:
                continue
            self._claim(confirmed)
            match = BankMatch(
                views=confirmed,
                match_type=MatchType.REFERENCE_PREFIX,
                method=ConfidenceMethod.REFERENCE_PREFIX_UNIQUE,
                reason_codes=[ReasonCode.TRUNCATED_BANK_REFERENCE],
                rule_ids=[RULE_BANK_PREFIX_REFERENCE],
                evidence=[
                    Evidence(
                        source="BANK",
                        record_id=v.record.bank_transaction_id,
                        fact=(
                            f"Narration {v.record.description!r} carries truncated key "
                            f"{prefix}, which resolves uniquely to "
                            f"{settlement.settlement_id} at payout amount "
                            f"{settlement.net_amount_paisa} paise"
                        ),
                        amount_paisa=v.record.credit_amount_paisa,
                        detail={"rule_id": RULE_BANK_PREFIX_REFERENCE, "prefix": prefix},
                    )
                    for v in confirmed
                ],
            )
            self._annotate(match, settlement)
            return match

        # --- layer 3: exact amount inside the date window ----------------
        window = self.config.settlement_date_tolerance_days
        for view in self._unclaimed(
            self.index.credits_by_amount.get(settlement.net_amount_paisa, [])
        ):
            if not view.looks_like_gateway_payout:
                continue
            delta = days_between(
                view.record.transaction_date, settlement.settlement_date
            )
            if delta is None or abs(delta) > window:
                continue
            self._claim([view])
            match = BankMatch(
                views=[view],
                match_type=MatchType.AMOUNT_DATE_WINDOW,
                method=ConfidenceMethod.AMOUNT_DATE_COUNTERPARTY_COMPOSITE,
                rule_ids=[RULE_BANK_AMOUNT_DATE],
                evidence=[
                    Evidence(
                        source="BANK",
                        record_id=view.record.bank_transaction_id,
                        fact=(
                            f"Credit of {view.record.credit_amount_paisa} paise equals "
                            f"the payout exactly, lands {delta:+d} days from the "
                            f"settlement date (window +/-{window}), and the narration "
                            f"identifies the gateway"
                        ),
                        amount_paisa=view.record.credit_amount_paisa,
                        detail={
                            "rule_id": RULE_BANK_AMOUNT_DATE,
                            "date_delta_days": delta,
                        },
                    )
                ],
            )
            self._annotate(match, settlement)
            return match

        # --- layer 4: dynamic rounding / amount tolerance rules ----------
        rules_set = getattr(self.index, "rules", None)
        if rules_set and getattr(rules_set, "amount_tolerance_rules", None):
            for view in self._unclaimed(self.index.bank_views):
                if not view.is_credit:
                    continue
                var_paisa = view.record.credit_amount_paisa - settlement.net_amount_paisa
                gateway_name = getattr(settlement, "gateway", None) or getattr(settlement, "counterparty", None)
                rule_id = rules_set.check_amount_tolerance(var_paisa, gateway_name)
                if rule_id:
                    delta = days_between(view.record.transaction_date, settlement.settlement_date)
                    if delta is not None and abs(delta) <= 7:
                        self._claim([view])
                        match = BankMatch(
                            views=[view],
                            match_type=MatchType.AMOUNT_DATE_WINDOW,
                            method=ConfidenceMethod.AMOUNT_DATE_COUNTERPARTY_COMPOSITE,
                            reason_codes=[ReasonCode.PROMOTED_RULE_APPLIED],
                            rule_ids=[rule_id, RULE_BANK_AMOUNT_DATE],
                            evidence=[
                                Evidence(
                                    source="BANK",
                                    record_id=view.record.bank_transaction_id,
                                    fact=(
                                        f"Dynamic rule {rule_id} matched credit of {view.record.credit_amount_paisa} paise "
                                        f"with payout of {settlement.net_amount_paisa} paise (variance {var_paisa:+d} paise)."
                                    ),
                                    amount_paisa=view.record.credit_amount_paisa,
                                    detail={"rule_id": rule_id, "variance_paisa": var_paisa},
                                )
                            ],
                        )
                        self._annotate(match, settlement)
                        return match

        return BankMatch(reason_codes=[ReasonCode.MISSING_BANK_TRANSACTION])

    def _annotate(self, match: BankMatch, settlement: SettlementRecord) -> None:
        """Add the secondary observations a reviewer needs to see."""
        # A match sourced from a promoted rule is labelled as such, so an
        # operator can always tell which links exist because a rule was
        # promoted rather than because the built-in layers found them.
        for view in match.views:
            for key, rule_id in view.dynamic_keys:
                if key in view.numeric_keys:
                    match.reason_codes.append(ReasonCode.PROMOTED_RULE_APPLIED)
                    match.rule_ids.append(rule_id)
                    match.evidence.append(
                        Evidence(
                            source="BANK",
                            record_id=view.record.bank_transaction_id,
                            fact=(
                                f"Settlement key {key} was recovered from narration "
                                f"{view.record.description!r} by promoted rule "
                                f"{rule_id}; the built-in extractor found nothing "
                                f"usable in it"
                            ),
                            detail={"rule_id": rule_id, "recovered_key": key},
                        )
                    )
                    break

        if len(match.views) > 1:
            match.reason_codes.append(ReasonCode.DUPLICATE_BANK_TRANSACTION)

        if any(v.date_was_reformatted for v in match.views):
            match.reason_codes.append(ReasonCode.DATE_FORMAT_NORMALIZED)
            for v in match.views:
                if v.date_was_reformatted:
                    match.evidence.append(
                        Evidence(
                            source="BANK",
                            record_id=v.record.bank_transaction_id,
                            fact=(
                                f"Value date {v.record.raw.get('transaction_date')!r} "
                                f"normalized to "
                                f"{v.record.transaction_date.isoformat()}"
                            ),
                            detail={"rule_id": "RULE-NORM-010"},
                        )
                    )

        for v in match.views:
            if v.record.credit_amount_paisa != settlement.net_amount_paisa:
                match.reason_codes.append(ReasonCode.BANK_AMOUNT_VARIANCE)
                break

    def unclaimed_credits(self) -> List[BankView]:
        """Credits no settlement was able to account for, in statement order."""
        return [
            v
            for v in self.index.bank_views
            if v.is_credit and v.record.bank_transaction_id not in self.claimed
        ]
