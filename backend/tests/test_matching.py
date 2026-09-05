"""Matching layer tests: identifiers, N:M shapes, duplicates, date tolerance."""

from __future__ import annotations

from datetime import timedelta

from app.domain.enums import MatchType, ReconciliationStatus
from app.services.normalization.dates import parse_date, within_tolerance
from app.services.normalization.references import extract_reference
from app.services.normalization.text import counterparty_key, numeric_invoice_key
from tests.conftest import (
    ORDER_DATE,
    SETTLE_DATE,
    make_bank_credit,
    make_dataset,
    make_invoice,
    make_order,
    make_settlement,
    simple_case,
)


def only(output):
    """The single order-derived result in a one-order dataset."""
    return next(r for r in output.results if r.order_id is not None)


# --- 6. exact payment matching -------------------------------------------
def test_exact_payment_match_is_fully_proved(engine):
    result = only(engine.run(simple_case()))
    assert result.status is ReconciliationStatus.MATCHED
    assert result.match_type is MatchType.EXACT_PAYMENT_ID
    assert result.confidence == 1.0
    assert result.variance_paisa == 0
    assert result.reason_codes == []
    assert "ORD-10001" in result.source_records
    assert "SET-10001" in result.source_records
    assert "BANK-77001" in result.source_records


def test_matched_result_carries_a_reconstructable_calculation(engine):
    result = only(engine.run(simple_case()))
    expressions = " ".join(line.expression for line in result.calculation)
    assert "1000000 x 200/10000 = 20000" in expressions   # fee
    assert "20000 x 1800/10000 = 3600" in expressions      # GST on fee
    assert "1000000 x 10/10000 = 1000" in expressions      # TDS
    assert result.expected_amount_paisa == 1_000_000 - 20_000 - 3_600 - 1_000


# --- 7. N:M matching ------------------------------------------------------
def test_aggregated_settlement_covers_three_payments(engine):
    orders = [
        make_order(f"ORD-1000{i}", f"PAY-8900{i}", f"INV-1000{i}", gross=g)
        for i, g in enumerate([120_000, 340_000, 55_000], start=1)
    ]
    total = sum(o.gross_amount_paisa for o in orders)
    from app.services.accounting.fees import compute_fee_breakdown
    from app.core.config import AccountingConfig

    parts = [compute_fee_breakdown(o.gross_amount_paisa, AccountingConfig()) for o in orders]
    settlement = make_settlement(
        payment_ids=[o.payment_id for o in orders],
        gross=total,
        fee_override=sum(p.gateway_fee_paisa for p in parts),
        gst_override=sum(p.gst_on_fee_paisa for p in parts),
        tds_override=sum(p.tds_paisa for p in parts),
        net_override=sum(p.net_amount_paisa for p in parts),
    )
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    invoices = [make_invoice(o.invoice_id, total=o.gross_amount_paisa) for o in orders]
    output = engine.run(make_dataset(orders, [settlement], [credit], invoices))

    assert len(output.results) == 3
    for result in output.results:
        assert result.status is ReconciliationStatus.MATCHED
        assert result.match_type is MatchType.AGGREGATED_SETTLEMENT
        assert result.confidence == 1.0
        assert "AGGREGATED_SETTLEMENT" in [c.value for c in result.reason_codes]
    # One credit serves all three; none of them may claim it is missing.
    assert all(r.bank_transaction_ids == ["BANK-77001"] for r in output.results)


def test_split_settlement_sums_two_legs(engine):
    order = make_order(gross=1_000_000)
    leg_a = make_settlement("SET-10001", gross=600_000)
    leg_b = make_settlement("SET-10002", gross=400_000, settlement_date=SETTLE_DATE)
    credits = [
        make_bank_credit("BANK-77001", leg_a.net_amount_paisa, "RZP SET-10001", "SET-10001"),
        make_bank_credit("BANK-77002", leg_b.net_amount_paisa, "RZP SET-10002", "SET-10002"),
    ]
    result = only(
        engine.run(make_dataset([order], [leg_a, leg_b], credits, [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert result.match_type is MatchType.SPLIT_SETTLEMENT
    assert "SPLIT_SETTLEMENT" in [c.value for c in result.reason_codes]
    assert sorted(result.settlement_ids) == ["SET-10001", "SET-10002"]
    assert len(result.bank_transaction_ids) == 2
    assert result.variance_paisa == 0


def test_even_split_is_not_mistaken_for_a_duplicate(engine):
    """Two identical-amount legs summing to the gross are a split, not a duplicate."""
    order = make_order(gross=1_000_000)
    leg_a = make_settlement("SET-10001", gross=500_000)
    leg_b = make_settlement("SET-10002", gross=500_000)
    credits = [
        make_bank_credit("BANK-77001", leg_a.net_amount_paisa, "RZP SET-10001", "SET-10001"),
        make_bank_credit("BANK-77002", leg_b.net_amount_paisa, "RZP SET-10002", "SET-10002"),
    ]
    result = only(
        engine.run(make_dataset([order], [leg_a, leg_b], credits, [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert result.match_type is MatchType.SPLIT_SETTLEMENT


# --- 9. duplicate detection ----------------------------------------------
def test_duplicate_settlement_exposes_the_doubled_amount(engine):
    order = make_order(gross=1_000_000)
    original = make_settlement("SET-10001", gross=1_000_000)
    duplicate = make_settlement("SET-10002", gross=1_000_000)
    credit = make_bank_credit(amount=original.net_amount_paisa)
    result = only(
        engine.run(
            make_dataset([order], [original, duplicate], [credit], [make_invoice()])
        )
    )
    assert result.status is ReconciliationStatus.DUPLICATE
    assert "DUPLICATE_SETTLEMENT" in [c.value for c in result.reason_codes]
    # Exposure is the second payout, not zero.
    assert result.variance_paisa == original.net_amount_paisa
    assert result.unexplained_value_paisa == original.net_amount_paisa
    assert sorted(result.settlement_ids) == ["SET-10001", "SET-10002"]


def test_duplicate_bank_credit_is_flagged(engine):
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    net = settlement.net_amount_paisa
    credits = [
        make_bank_credit("BANK-77001", net),
        make_bank_credit("BANK-77002", net),
    ]
    result = only(
        engine.run(make_dataset([order], [settlement], credits, [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.DUPLICATE
    assert "DUPLICATE_BANK_TRANSACTION" in [c.value for c in result.reason_codes]
    assert len(result.bank_transaction_ids) == 2


# --- 12. date tolerance ---------------------------------------------------
def test_date_window_helper():
    assert within_tolerance(parse_date("2026-06-05"), parse_date("2026-06-03"), 3)
    assert not within_tolerance(parse_date("2026-06-09"), parse_date("2026-06-03"), 3)


def test_credit_inside_the_date_window_matches_without_a_reference(engine):
    """No usable reference: matched on exact amount + window + gateway narration."""
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    credit = make_bank_credit(
        amount=settlement.net_amount_paisa,
        description="RAZORPAY PAYOUT NO REFERENCE",
        reference="",
        transaction_date=SETTLE_DATE + timedelta(days=2),
    )
    result = only(
        engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert result.confidence == 0.90
    assert result.confidence_method.value == "AMOUNT_DATE_COUNTERPARTY_COMPOSITE"


def test_credit_outside_the_date_window_does_not_match(engine):
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    credit = make_bank_credit(
        amount=settlement.net_amount_paisa,
        description="RAZORPAY PAYOUT NO REFERENCE",
        reference="",
        transaction_date=SETTLE_DATE + timedelta(days=30),
    )
    result = only(
        engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.PARTIAL_MATCH
    assert "MISSING_BANK_TRANSACTION" in [c.value for c in result.reason_codes]


def test_truncated_reference_resolves_uniquely(engine):
    order = make_order(gross=1_000_000)
    settlement = make_settlement("SET-10291", gross=1_000_000)
    credit = make_bank_credit(
        amount=settlement.net_amount_paisa,
        description="RZP SET-1029",
        reference="1029",
    )
    result = only(
        engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert result.confidence == 0.95
    assert "TRUNCATED_BANK_REFERENCE" in [c.value for c in result.reason_codes]


# --- 13. invoice typo + alias normalization -------------------------------
def test_invoice_typo_folds_to_the_same_key():
    assert numeric_invoice_key("INV-10001") == numeric_invoice_key("INV-1O001")
    assert numeric_invoice_key("INV-10001") != numeric_invoice_key("INV-10002")


def test_invoice_typo_is_resolved_and_labelled(engine):
    order = make_order(invoice_id="INV-10001", gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    invoice = make_invoice("INV-1O001", total=1_000_000)  # letter O for zero
    result = only(engine.run(make_dataset([order], [settlement], [credit], [invoice])))
    assert result.status is ReconciliationStatus.MATCHED
    assert result.invoice_id == "INV-1O001"
    assert "INVOICE_TYPO_RESOLVED" in [c.value for c in result.reason_codes]


def test_counterparty_alias_folds_legal_suffixes():
    assert counterparty_key("Acme Retail Pvt Ltd") == counterparty_key("ACME  RETAIL.")
    assert counterparty_key("Acme Retail") != counterparty_key("Acme Wholesale")


def test_counterparty_alias_is_resolved_and_labelled(engine):
    order = make_order(customer="Acme Retail", gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    invoice = make_invoice(customer="Acme Retail Pvt Ltd", total=1_000_000)
    result = only(engine.run(make_dataset([order], [settlement], [credit], [invoice])))
    assert result.status is ReconciliationStatus.MATCHED
    assert "COUNTERPARTY_ALIAS_RESOLVED" in [c.value for c in result.reason_codes]


def test_date_format_difference_is_normalized_and_labelled(engine):
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    credit = make_bank_credit(
        amount=settlement.net_amount_paisa, raw_date="03/06/2026"
    )
    result = only(
        engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    )
    assert result.status is ReconciliationStatus.MATCHED
    assert "DATE_FORMAT_NORMALIZED" in [c.value for c in result.reason_codes]


def test_messy_narrations_all_yield_the_same_key():
    keys = [
        extract_reference(d).numeric_keys
        for d in (
            "RAZORPAY SETTLEMENT SET-10291",
            "RAZORPAY SETTLE 10291",
            "RZP SET-10291",
            "Settlement payout / 10291",
            "NEFT-RZPSET10291-HDFC",
            "rzp  set-10291",
        )
    ]
    assert all("10291" in k for k in keys)
