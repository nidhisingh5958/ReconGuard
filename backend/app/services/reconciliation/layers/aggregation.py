"""Layer 4 - N:M settlement matching.

A payment and a payout are not always one to one. Four shapes occur:

* SIMPLE     - one payment, one settlement.
* AGGREGATED - N payments consolidated into one payout.
* SPLIT      - one payment paid out over N settlements.
* DUPLICATE  - the same payment settled more than once for the same amount.

This is deliberately a matching service over grouped, indexed data rather than
string comparison. The shape is decided from the covered-payment sets and the
amounts, and the decision is recorded so the UI can show why a row was treated
as an aggregate rather than as a shortfall.

Isolating the shape decision here means the grouping algorithm can be optimised
or replaced without touching classification or the accounting layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence

from app.domain.enums import MatchType, ReasonCode
from app.domain.reconciliation import Evidence
from app.domain.sources import OrderRecord, SettlementRecord
from app.services.reconciliation.indexes import ReconciliationIndex

RULE_GROUP_SHAPE = "RULE-MATCH-010"
RULE_AGGREGATION = "RULE-MATCH-011"
RULE_SPLIT = "RULE-MATCH-012"
RULE_DUPLICATE = "RULE-MATCH-013"


class Relationship(str, Enum):
    SIMPLE = "SIMPLE"
    AGGREGATED = "AGGREGATED"
    SPLIT = "SPLIT"
    DUPLICATE = "DUPLICATE"


MATCH_TYPE_FOR_RELATIONSHIP: Dict[Relationship, MatchType] = {
    Relationship.SIMPLE: MatchType.EXACT_PAYMENT_ID,
    Relationship.AGGREGATED: MatchType.AGGREGATED_SETTLEMENT,
    Relationship.SPLIT: MatchType.SPLIT_SETTLEMENT,
    Relationship.DUPLICATE: MatchType.EXACT_PAYMENT_ID,
}

REASON_FOR_RELATIONSHIP: Dict[Relationship, List[ReasonCode]] = {
    Relationship.SIMPLE: [],
    Relationship.AGGREGATED: [ReasonCode.AGGREGATED_SETTLEMENT],
    Relationship.SPLIT: [ReasonCode.SPLIT_SETTLEMENT],
    Relationship.DUPLICATE: [ReasonCode.DUPLICATE_SETTLEMENT],
}


@dataclass
class SettlementGroup:
    """The settlement side of one payment, with its shape already decided."""

    payment_id: str
    relationship: Relationship
    settlements: List[SettlementRecord] = field(default_factory=list)
    duplicate_settlements: List[SettlementRecord] = field(default_factory=list)
    covered_payment_ids: List[str] = field(default_factory=list)
    component_gross_amounts: List[int] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    reason_codes: List[ReasonCode] = field(default_factory=list)
    rule_ids: List[str] = field(default_factory=list)

    @property
    def primary(self) -> SettlementRecord:
        return self.settlements[0]

    @property
    def settlement_ids(self) -> List[str]:
        return [s.settlement_id for s in self.settlements]

    @property
    def all_settlement_ids(self) -> List[str]:
        return self.settlement_ids + [
            s.settlement_id for s in self.duplicate_settlements
        ]

    @property
    def reported_net_paisa(self) -> int:
        return sum(s.net_amount_paisa for s in self.settlements)

    @property
    def reported_gross_paisa(self) -> int:
        return sum(s.gross_amount_paisa for s in self.settlements)

    @property
    def reported_fee_paisa(self) -> int:
        return sum(s.gateway_fee_paisa for s in self.settlements)

    @property
    def reported_gst_paisa(self) -> int:
        return sum(s.gst_on_fee_paisa for s in self.settlements)

    @property
    def reported_tds_paisa(self) -> int:
        return sum(s.tds_paisa for s in self.settlements)

    @property
    def reported_refund_paisa(self) -> int:
        return sum(s.refund_adjustment_paisa for s in self.settlements)

    @property
    def duplicate_net_paisa(self) -> int:
        return sum(s.net_amount_paisa for s in self.duplicate_settlements)

    @property
    def match_type(self) -> MatchType:
        return MATCH_TYPE_FOR_RELATIONSHIP[self.relationship]


def _is_same_payout(a: SettlementRecord, b: SettlementRecord) -> bool:
    """Two settlements look like the same payout: same coverage, same amounts."""
    return (
        a.gross_amount_paisa == b.gross_amount_paisa
        and a.net_amount_paisa == b.net_amount_paisa
        and sorted(a.covered_payment_ids()) == sorted(b.covered_payment_ids())
    )


def _claims_whole_payment(
    settlement: SettlementRecord, order: OrderRecord
) -> bool:
    """True when this settlement says it is paying out the entire order gross."""
    return settlement.gross_amount_paisa == order.gross_amount_paisa


def group_settlements(
    order: OrderRecord,
    settlements: Sequence[SettlementRecord],
    index: ReconciliationIndex,
) -> SettlementGroup:
    """Decide the payment-to-payout shape and gather the expected components."""
    ordered = sorted(settlements, key=lambda s: s.settlement_id)
    payment_id = order.payment_id

    # Two settlements of the same amount for one payment are ambiguous on their
    # face: they could be a double payout, or an even two-way split. The gross
    # discriminates, and it does so deterministically. A settlement that claims
    # the WHOLE order gross is paying the payment in full, so a second one
    # claiming the same is a duplicate. Settlements whose grosses SUM to the
    # order gross are legs of a split, however similar their amounts look.
    sum_of_gross = sum(s.gross_amount_paisa for s in ordered)
    all_claim_whole = all(_claims_whole_payment(s, order) for s in ordered)
    is_split = (
        len(ordered) > 1
        and not all_claim_whole
        and sum_of_gross == order.gross_amount_paisa
    )

    unique: List[SettlementRecord] = []
    duplicates: List[SettlementRecord] = []
    if not is_split:
        for settlement in ordered:
            if any(_is_same_payout(settlement, kept) for kept in unique):
                duplicates.append(settlement)
            else:
                unique.append(settlement)
    else:
        unique = list(ordered)

    if duplicates:
        primary = unique[0]
        group = SettlementGroup(
            payment_id=payment_id,
            relationship=Relationship.DUPLICATE,
            settlements=[primary],
            duplicate_settlements=duplicates,
            covered_payment_ids=primary.covered_payment_ids(),
            component_gross_amounts=[order.gross_amount_paisa],
            reason_codes=list(REASON_FOR_RELATIONSHIP[Relationship.DUPLICATE]),
            rule_ids=[RULE_DUPLICATE],
        )
        for dup in duplicates:
            group.evidence.append(
                Evidence(
                    source="SETTLEMENTS",
                    record_id=dup.settlement_id,
                    fact=(
                        f"Settlement {dup.settlement_id} repeats the payout already "
                        f"recorded by {primary.settlement_id}: same covered payments, "
                        f"same gross {dup.gross_amount_paisa}, same net "
                        f"{dup.net_amount_paisa}"
                    ),
                    amount_paisa=dup.net_amount_paisa,
                    detail={"rule_id": RULE_DUPLICATE},
                )
            )
        return group

    if len(unique) == 1:
        settlement = unique[0]
        covered = settlement.covered_payment_ids()
        if len(covered) > 1:
            components: List[int] = []
            evidence: List[Evidence] = []
            for pid in covered:
                sibling = index.orders_by_payment_id.get(pid)
                if sibling is None:
                    continue
                components.append(sibling.gross_amount_paisa)
                evidence.append(
                    Evidence(
                        source="ORDERS",
                        record_id=sibling.order_id,
                        fact=(
                            f"Payment {pid} contributes gross "
                            f"{sibling.gross_amount_paisa} paise to aggregated payout "
                            f"{settlement.settlement_id}"
                        ),
                        amount_paisa=sibling.gross_amount_paisa,
                        detail={"rule_id": RULE_AGGREGATION},
                    )
                )
            return SettlementGroup(
                payment_id=payment_id,
                relationship=Relationship.AGGREGATED,
                settlements=[settlement],
                covered_payment_ids=covered,
                component_gross_amounts=components,
                evidence=evidence,
                reason_codes=list(REASON_FOR_RELATIONSHIP[Relationship.AGGREGATED]),
                rule_ids=[RULE_AGGREGATION],
            )

        return SettlementGroup(
            payment_id=payment_id,
            relationship=Relationship.SIMPLE,
            settlements=[settlement],
            covered_payment_ids=covered,
            component_gross_amounts=[order.gross_amount_paisa],
            rule_ids=[RULE_GROUP_SHAPE],
        )

    # Several distinct settlements for one payment: a split payout. Each leg
    # carries its own gross, so each leg is verified against its own fees.
    evidence = [
        Evidence(
            source="SETTLEMENTS",
            record_id=s.settlement_id,
            fact=(
                f"Split leg {s.settlement_id} carries gross {s.gross_amount_paisa} "
                f"paise, net {s.net_amount_paisa} paise, value date "
                f"{s.settlement_date.isoformat()}"
            ),
            amount_paisa=s.net_amount_paisa,
            detail={"rule_id": RULE_SPLIT},
        )
        for s in unique
    ]
    return SettlementGroup(
        payment_id=payment_id,
        relationship=Relationship.SPLIT,
        settlements=unique,
        covered_payment_ids=[payment_id],
        component_gross_amounts=[s.gross_amount_paisa for s in unique],
        evidence=evidence,
        reason_codes=list(REASON_FOR_RELATIONSHIP[Relationship.SPLIT]),
        rule_ids=[RULE_SPLIT],
    )
