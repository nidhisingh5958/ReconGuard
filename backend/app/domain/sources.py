"""Raw source records, exactly as ingested. These are never mutated.

Amount fields carry the suffix ``_paisa`` to make the unit impossible to
misread. The raw JSON on disk stores paise integers too - there is no rupee
float anywhere in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class OrderRecord:
    """Source A - commerce orders."""

    order_id: str
    customer_id: str
    customer_name: str
    invoice_id: str
    payment_id: str
    gross_amount_paisa: int
    refund_amount_paisa: int
    currency: str
    order_date: date
    status: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SettlementRecord:
    """Source B - Razorpay settlement records.

    ``payment_ids`` supports aggregated settlements (N payments -> 1 payout).
    ``payment_id`` remains the primary leg for spec compatibility.
    """

    settlement_id: str
    payment_id: str
    gross_amount_paisa: int
    gateway_fee_paisa: int
    gst_on_fee_paisa: int
    tds_paisa: int
    refund_adjustment_paisa: int
    net_amount_paisa: int
    settlement_date: date
    status: str
    payment_ids: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def covered_payment_ids(self) -> List[str]:
        return self.payment_ids or [self.payment_id]


@dataclass(slots=True)
class BankTransactionRecord:
    """Source C - bank statement lines, with deliberately messy descriptions."""

    bank_transaction_id: str
    transaction_date: date
    description: str
    reference: str
    credit_amount_paisa: int
    debit_amount_paisa: int
    balance_paisa: int
    transaction_type: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InvoiceRecord:
    """Source D - invoice / tax register."""

    invoice_id: str
    customer_name: str
    gstin: str
    invoice_date: date
    taxable_amount_paisa: int
    gst_amount_paisa: int
    total_amount_paisa: int
    tds_amount_paisa: int
    status: str
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GroundTruthAnomaly:
    """Known-truth label for an injected anomaly (evaluation only, never in UI)."""

    anomaly_id: str
    anomaly_type: str
    description: str
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    settlement_id: Optional[str] = None
    bank_transaction_id: Optional[str] = None
    invoice_id: Optional[str] = None
    expected_status: Optional[str] = None
    detected_on: str = "order"
    expected_reason_codes: List[str] = field(default_factory=list)
    amount_paisa: int = 0


@dataclass(slots=True)
class SourceDataset:
    """Everything the engine needs for one reconciliation run."""

    orders: List[OrderRecord] = field(default_factory=list)
    settlements: List[SettlementRecord] = field(default_factory=list)
    bank_transactions: List[BankTransactionRecord] = field(default_factory=list)
    invoices: List[InvoiceRecord] = field(default_factory=list)
    ground_truth: List[GroundTruthAnomaly] = field(default_factory=list)
    dataset_id: str = "default"
    mode: str = "messy"
    seed: int = 42

    def record_count(self) -> int:
        return (
            len(self.orders)
            + len(self.settlements)
            + len(self.bank_transactions)
            + len(self.invoices)
        )
