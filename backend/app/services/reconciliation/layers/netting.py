"""Layer 5 - refund and chargeback netting.

The rule this layer exists to enforce: when a refund or a chargeback is netted
inside a settlement, the original order is NOT missing. Reporting it as missing
would be the single most damaging false positive this system could produce,
because it sends an operator hunting for money that was correctly clawed back.

Instead we produce an AdjustmentRecord that names the refunded payment, the
settlement that absorbed it, the amount, and the evidence for all three.

Attribution is taken from the source data, never inferred:

* if the settlement itemises ``netted_refund_payment_ids`` (which real gateway
  settlement reports do), the refund is attributed to exactly those payments;
* otherwise it is attributed to the payments the settlement itself covers.

A refund we cannot attribute is left unattributed and surfaced, rather than
being quietly spread across whatever happens to be nearby.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.ids import SequenceIdFactory
from app.domain.enums import AdjustmentType
from app.domain.reconciliation import AdjustmentRecord, Evidence
from app.domain.sources import SettlementRecord
from app.services.reconciliation.indexes import ReconciliationIndex

RULE_REFUND_ATTRIBUTION = "RULE-NET-010"
RULE_CHARGEBACK_DETECT = "RULE-NET-011"

NETTED_REFUND_FIELD = "netted_refund_payment_ids"


@dataclass
class NettingResult:
    """Everything the classifier needs to know about netted movements."""

    adjustments_by_settlement: Dict[str, List[AdjustmentRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    adjustments_by_payment: Dict[str, List[AdjustmentRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    chargebacks_by_settlement: Dict[str, List[AdjustmentRecord]] = field(
        default_factory=lambda: defaultdict(list)
    )
    unattributed: List[AdjustmentRecord] = field(default_factory=list)

    def for_settlement(self, settlement_id: str) -> List[AdjustmentRecord]:
        return self.adjustments_by_settlement.get(settlement_id, [])

    def for_payment(self, payment_id: str) -> List[AdjustmentRecord]:
        return self.adjustments_by_payment.get(payment_id, [])

    def chargebacks_for(self, settlement_id: str) -> List[AdjustmentRecord]:
        return self.chargebacks_by_settlement.get(settlement_id, [])


def _refund_target_payments(settlement: SettlementRecord) -> List[str]:
    itemised = settlement.raw.get(NETTED_REFUND_FIELD)
    if itemised:
        return list(itemised)
    return settlement.covered_payment_ids()


def resolve_netting(index: ReconciliationIndex) -> NettingResult:
    """Build adjustment records for every netted refund and chargeback."""
    result = NettingResult()
    ids = SequenceIdFactory("ADJ", width=5)

    # --- refunds netted inside a payout ----------------------------------
    for settlement_id in sorted(index.settlements_by_id):
        settlement = index.settlements_by_id[settlement_id]
        amount = settlement.refund_adjustment_paisa
        if not amount:
            continue

        targets = _refund_target_payments(settlement)
        for payment_id in targets:
            order = index.orders_by_payment_id.get(payment_id)
            is_self_netted = payment_id in settlement.covered_payment_ids()
            adjustment_type = (
                AdjustmentType.PARTIAL_REFUND
                if is_self_netted
                else AdjustmentType.REFUND_NETTING
            )
            evidence = [
                Evidence(
                    source="SETTLEMENTS",
                    record_id=settlement.settlement_id,
                    fact=(
                        f"Settlement reports refund_adjustment of {amount} paise "
                        f"attributed to {payment_id}"
                    ),
                    amount_paisa=amount,
                    detail={"rule_id": RULE_REFUND_ATTRIBUTION},
                )
            ]
            if order is not None:
                evidence.append(
                    Evidence(
                        source="ORDERS",
                        record_id=order.order_id,
                        fact=(
                            f"Order {order.order_id} records refund_amount "
                            f"{order.refund_amount_paisa} paise, status "
                            f"{order.status!r}"
                        ),
                        amount_paisa=order.refund_amount_paisa,
                    )
                )
            adjustment = AdjustmentRecord(
                adjustment_id=ids.next(),
                adjustment_type=adjustment_type,
                amount_paisa=amount,
                source_record=settlement.settlement_id,
                related_payment=payment_id,
                related_settlement=settlement.settlement_id,
                evidence=evidence,
                description=(
                    f"Refund of {amount} paise for {payment_id} netted inside "
                    f"settlement {settlement.settlement_id}"
                ),
            )
            result.adjustments_by_settlement[settlement.settlement_id].append(adjustment)
            result.adjustments_by_payment[payment_id].append(adjustment)
            if order is None:
                result.unattributed.append(adjustment)

    # --- chargebacks appearing as bank debits ----------------------------
    for key, views in index.debits_by_key.items():
        settlement_ids = index.settlement_key_to_ids.get(key, [])
        if not settlement_ids:
            continue
        for settlement_id in settlement_ids:
            settlement = index.settlements_by_id[settlement_id]
            for view in views:
                adjustment = AdjustmentRecord(
                    adjustment_id=ids.next(),
                    adjustment_type=AdjustmentType.CHARGEBACK,
                    amount_paisa=view.record.debit_amount_paisa,
                    source_record=view.record.bank_transaction_id,
                    related_payment=settlement.payment_id,
                    related_settlement=settlement_id,
                    evidence=[
                        Evidence(
                            source="BANK",
                            record_id=view.record.bank_transaction_id,
                            fact=(
                                f"Bank debit of {view.record.debit_amount_paisa} paise "
                                f"references settlement {settlement_id}: "
                                f"{view.record.description!r}"
                            ),
                            amount_paisa=view.record.debit_amount_paisa,
                            detail={"rule_id": RULE_CHARGEBACK_DETECT},
                        )
                    ],
                    description=(
                        f"Chargeback debit reverses settlement {settlement_id}"
                    ),
                )
                result.chargebacks_by_settlement[settlement_id].append(adjustment)

    return result
