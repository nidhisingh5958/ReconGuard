"""Builds CanonicalTransaction rows from raw source records.

Contract: this layer only ever *adds* a normalized view. Source dataclasses are
never mutated, and every transformation that actually changed a value leaves a
NormalizationStep behind so the audit trail can show original -> normalized
with the rule that did it.
"""

from __future__ import annotations

from typing import List

from app.core.ids import SequenceIdFactory
from app.domain.canonical import CanonicalTransaction, NormalizationStep
from app.domain.enums import SourceSystem, TransactionType
from app.domain.sources import (
    BankTransactionRecord,
    InvoiceRecord,
    OrderRecord,
    SettlementRecord,
    SourceDataset,
)
from app.services.normalization.references import extract_reference
from app.services.normalization.text import (
    RULE_COUNTERPARTY_ALIAS,
    RULE_INVOICE_NORMALIZE,
    RULE_TEXT_NORMALIZE,
    counterparty_key,
    normalize_identifier,
    numeric_invoice_key,
)

RULE_REFERENCE_NORMALIZE = "RULE-NORM-020"


def _step(field_name: str, original, normalized, rule: str) -> NormalizationStep:
    return NormalizationStep(
        field_name=field_name,
        original_value="" if original is None else str(original),
        normalized_value="" if normalized is None else str(normalized),
        rule=rule,
    )


def _changed_steps(candidates) -> List[NormalizationStep]:
    """Keep only the steps where normalization actually altered the value.

    A trace full of no-op rows buries the one transformation an auditor cares
    about, so identity transformations are dropped.
    """
    return [s for s in candidates if s.original_value != s.normalized_value]


class CanonicalNormalizer:
    """Turns a SourceDataset into canonical transactions, one per source row."""

    def __init__(self) -> None:
        self._ids = SequenceIdFactory("CAN", width=6)

    # -- individual source normalizers ------------------------------------
    def normalize_order(self, order: OrderRecord) -> CanonicalTransaction:
        cp_key = counterparty_key(order.customer_name)
        inv_key = numeric_invoice_key(order.invoice_id)
        trace = _changed_steps(
            [
                _step("customer_name", order.customer_name, cp_key, RULE_COUNTERPARTY_ALIAS),
                _step("invoice_id", order.invoice_id, inv_key, RULE_INVOICE_NORMALIZE),
            ]
        )
        return CanonicalTransaction(
            canonical_id=self._ids.next(),
            source=SourceSystem.ORDERS,
            source_record_id=order.order_id,
            transaction_type=TransactionType.ORDER_PAYMENT,
            amount_paisa=order.gross_amount_paisa,
            date=order.order_date,
            reference=normalize_identifier(order.payment_id),
            counterparty=cp_key,
            invoice_id=order.invoice_id,
            payment_id=order.payment_id,
            order_id=order.order_id,
            currency=order.currency,
            metadata={
                "status": order.status,
                "refund_amount_paisa": order.refund_amount_paisa,
                "customer_id": order.customer_id,
                "customer_name_original": order.customer_name,
                "counterparty_key": cp_key,
                "invoice_numeric_key": inv_key,
            },
            normalization_trace=trace,
        )

    def normalize_settlement(self, s: SettlementRecord) -> CanonicalTransaction:
        trace = _changed_steps(
            [
                _step(
                    "settlement_id",
                    s.settlement_id,
                    normalize_identifier(s.settlement_id),
                    RULE_TEXT_NORMALIZE,
                )
            ]
        )
        return CanonicalTransaction(
            canonical_id=self._ids.next(),
            source=SourceSystem.SETTLEMENTS,
            source_record_id=s.settlement_id,
            transaction_type=TransactionType.SETTLEMENT_PAYOUT,
            amount_paisa=s.net_amount_paisa,
            date=s.settlement_date,
            reference=normalize_identifier(s.settlement_id),
            counterparty="RAZORPAY",
            payment_id=s.payment_id,
            settlement_id=s.settlement_id,
            metadata={
                "status": s.status,
                "gross_amount_paisa": s.gross_amount_paisa,
                "gateway_fee_paisa": s.gateway_fee_paisa,
                "gst_on_fee_paisa": s.gst_on_fee_paisa,
                "tds_paisa": s.tds_paisa,
                "refund_adjustment_paisa": s.refund_adjustment_paisa,
                "covered_payment_ids": s.covered_payment_ids(),
            },
            normalization_trace=trace,
        )

    def normalize_bank_transaction(
        self, b: BankTransactionRecord
    ) -> CanonicalTransaction:
        extracted = extract_reference(b.description, b.reference)
        is_credit = b.credit_amount_paisa > 0
        trace = _changed_steps(
            [
                _step(
                    "description",
                    b.description,
                    extracted.normalized,
                    RULE_REFERENCE_NORMALIZE,
                ),
                _step(
                    "reference",
                    b.reference,
                    ",".join(extracted.numeric_keys),
                    RULE_REFERENCE_NORMALIZE,
                ),
            ]
        )
        return CanonicalTransaction(
            canonical_id=self._ids.next(),
            source=SourceSystem.BANK,
            source_record_id=b.bank_transaction_id,
            transaction_type=(
                TransactionType.BANK_CREDIT if is_credit else TransactionType.BANK_DEBIT
            ),
            amount_paisa=b.credit_amount_paisa if is_credit else -b.debit_amount_paisa,
            date=b.transaction_date,
            reference=extracted.normalized,
            counterparty="BANK",
            metadata={
                "transaction_type": b.transaction_type,
                "balance_paisa": b.balance_paisa,
                "description_original": b.description,
                "reference_original": b.reference,
                "numeric_keys": extracted.numeric_keys,
                "token_keys": extracted.token_keys,
                "looks_like_gateway_payout": extracted.looks_like_gateway_payout,
            },
            normalization_trace=trace,
        )

    def normalize_invoice(self, i: InvoiceRecord) -> CanonicalTransaction:
        cp_key = counterparty_key(i.customer_name)
        inv_key = numeric_invoice_key(i.invoice_id)
        trace = _changed_steps(
            [
                _step("customer_name", i.customer_name, cp_key, RULE_COUNTERPARTY_ALIAS),
                _step("invoice_id", i.invoice_id, inv_key, RULE_INVOICE_NORMALIZE),
            ]
        )
        return CanonicalTransaction(
            canonical_id=self._ids.next(),
            source=SourceSystem.INVOICES,
            source_record_id=i.invoice_id,
            transaction_type=TransactionType.INVOICE,
            amount_paisa=i.total_amount_paisa,
            date=i.invoice_date,
            reference=normalize_identifier(i.invoice_id),
            counterparty=cp_key,
            invoice_id=i.invoice_id,
            metadata={
                "status": i.status,
                "gstin": i.gstin,
                "taxable_amount_paisa": i.taxable_amount_paisa,
                "gst_amount_paisa": i.gst_amount_paisa,
                "tds_amount_paisa": i.tds_amount_paisa,
                "customer_name_original": i.customer_name,
                "invoice_numeric_key": inv_key,
            },
            normalization_trace=trace,
        )

    # -- dataset level -----------------------------------------------------
    def normalize_dataset(self, dataset: SourceDataset) -> List[CanonicalTransaction]:
        canonical: List[CanonicalTransaction] = []
        canonical.extend(self.normalize_order(o) for o in dataset.orders)
        canonical.extend(self.normalize_settlement(s) for s in dataset.settlements)
        canonical.extend(
            self.normalize_bank_transaction(b) for b in dataset.bank_transactions
        )
        canonical.extend(self.normalize_invoice(i) for i in dataset.invoices)
        return canonical
