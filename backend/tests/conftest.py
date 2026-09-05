"""Shared fixtures and builders.

The builders construct minimal, hand-checkable datasets so a test can state a
single financial fact and assert exactly one behaviour. Correct fee values are
derived rather than typed, so a change to the configured rates does not silently
turn a passing test into a meaningless one.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

import pytest

from app.core.config import AccountingConfig, ReconciliationConfig
from app.domain.sources import (
    BankTransactionRecord,
    InvoiceRecord,
    OrderRecord,
    SettlementRecord,
    SourceDataset,
)
from app.services.accounting.fees import compute_fee_breakdown
from app.services.reconciliation.engine import ReconciliationEngine

ORDER_DATE = date(2026, 6, 1)
SETTLE_DATE = ORDER_DATE + timedelta(days=2)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    from app.core.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def accounting() -> AccountingConfig:
    """2% gateway fee, 18% GST on that fee, 0.10% TDS."""
    return AccountingConfig()


@pytest.fixture
def recon_config() -> ReconciliationConfig:
    return ReconciliationConfig()


@pytest.fixture
def engine(accounting, recon_config) -> ReconciliationEngine:
    return ReconciliationEngine(accounting=accounting, reconciliation=recon_config)


def make_order(
    order_id: str = "ORD-10001",
    payment_id: str = "PAY-89001",
    invoice_id: str = "INV-10001",
    gross: int = 10_000_00,
    refund: int = 0,
    customer: str = "Acme Retail",
    order_date: date = ORDER_DATE,
    status: str = "paid",
) -> OrderRecord:
    return OrderRecord(
        order_id=order_id,
        customer_id="CUS-100",
        customer_name=customer,
        invoice_id=invoice_id,
        payment_id=payment_id,
        gross_amount_paisa=gross,
        refund_amount_paisa=refund,
        currency="INR",
        order_date=order_date,
        status=status,
        raw={"order_id": order_id, "order_date": order_date.isoformat()},
    )


def make_settlement(
    settlement_id: str = "SET-10001",
    payment_ids: Optional[List[str]] = None,
    gross: int = 10_000_00,
    settlement_date: date = SETTLE_DATE,
    refund_adjustment: int = 0,
    netted_refund_payment_ids: Optional[List[str]] = None,
    net_override: Optional[int] = None,
    tds_override: Optional[int] = None,
    gst_override: Optional[int] = None,
    fee_override: Optional[int] = None,
    config: Optional[AccountingConfig] = None,
) -> SettlementRecord:
    """Build a settlement whose components are correct unless overridden."""
    cfg = config or AccountingConfig()
    payment_ids = payment_ids or ["PAY-89001"]
    breakdown = compute_fee_breakdown(gross, cfg)
    fee = fee_override if fee_override is not None else breakdown.gateway_fee_paisa
    gst = gst_override if gst_override is not None else breakdown.gst_on_fee_paisa
    tds = tds_override if tds_override is not None else breakdown.tds_paisa
    net = (
        net_override
        if net_override is not None
        else gross - fee - gst - tds - refund_adjustment
    )
    raw = {"settlement_id": settlement_id}
    if netted_refund_payment_ids:
        raw["netted_refund_payment_ids"] = netted_refund_payment_ids
    return SettlementRecord(
        settlement_id=settlement_id,
        payment_id=payment_ids[0],
        gross_amount_paisa=gross,
        gateway_fee_paisa=fee,
        gst_on_fee_paisa=gst,
        tds_paisa=tds,
        refund_adjustment_paisa=refund_adjustment,
        net_amount_paisa=net,
        settlement_date=settlement_date,
        status="processed",
        payment_ids=payment_ids,
        raw=raw,
    )


def make_bank_credit(
    bank_transaction_id: str = "BANK-77001",
    amount: int = 0,
    description: str = "RAZORPAY SETTLEMENT SET-10001",
    reference: str = "SET-10001",
    transaction_date: date = SETTLE_DATE,
    raw_date: Optional[str] = None,
) -> BankTransactionRecord:
    return BankTransactionRecord(
        bank_transaction_id=bank_transaction_id,
        transaction_date=transaction_date,
        description=description,
        reference=reference,
        credit_amount_paisa=amount,
        debit_amount_paisa=0,
        balance_paisa=0,
        transaction_type="CREDIT",
        raw={
            "bank_transaction_id": bank_transaction_id,
            "transaction_date": raw_date or transaction_date.isoformat(),
        },
    )


def make_bank_debit(
    bank_transaction_id: str = "BANK-79001",
    amount: int = 0,
    description: str = "CHARGEBACK DEBIT RZP SET-10001",
    reference: str = "SET-10001",
    transaction_date: date = SETTLE_DATE + timedelta(days=4),
) -> BankTransactionRecord:
    return BankTransactionRecord(
        bank_transaction_id=bank_transaction_id,
        transaction_date=transaction_date,
        description=description,
        reference=reference,
        credit_amount_paisa=0,
        debit_amount_paisa=amount,
        balance_paisa=0,
        transaction_type="DEBIT",
        raw={"bank_transaction_id": bank_transaction_id},
    )


def make_invoice(
    invoice_id: str = "INV-10001",
    customer: str = "Acme Retail",
    total: int = 10_000_00,
    invoice_date: date = ORDER_DATE,
) -> InvoiceRecord:
    taxable = round(total * 100 / 118)
    return InvoiceRecord(
        invoice_id=invoice_id,
        customer_name=customer,
        gstin="27AABCU9603R1ZX",
        invoice_date=invoice_date,
        taxable_amount_paisa=taxable,
        gst_amount_paisa=total - taxable,
        total_amount_paisa=total,
        tds_amount_paisa=0,
        status="issued",
        raw={"invoice_id": invoice_id},
    )


def make_dataset(
    orders=None, settlements=None, bank=None, invoices=None, mode="test"
) -> SourceDataset:
    return SourceDataset(
        orders=list(orders or []),
        settlements=list(settlements or []),
        bank_transactions=list(bank or []),
        invoices=list(invoices or []),
        dataset_id="unit-test",
        mode=mode,
        seed=0,
    )


def simple_case(gross: int = 10_000_00, config: Optional[AccountingConfig] = None):
    """A single order that reconciles perfectly end to end."""
    cfg = config or AccountingConfig()
    order = make_order(gross=gross)
    settlement = make_settlement(gross=gross, config=cfg)
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    invoice = make_invoice(total=gross)
    return make_dataset([order], [settlement], [credit], [invoice])
