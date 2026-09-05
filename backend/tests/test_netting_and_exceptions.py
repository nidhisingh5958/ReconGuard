"""Netting, refunds, chargebacks, and the honest-exception behaviours."""

from __future__ import annotations

from datetime import timedelta

from app.domain.enums import AdjustmentType, ReconciliationStatus
from tests.conftest import (
    SETTLE_DATE,
    make_bank_credit,
    make_bank_debit,
    make_dataset,
    make_invoice,
    make_order,
    make_settlement,
)


def result_for(output, order_id):
    return next(r for r in output.results if r.order_id == order_id)


# --- 8. refund netting ----------------------------------------------------
def test_partial_refund_netted_in_the_same_settlement(engine):
    refund = 250_000
    order = make_order(gross=1_000_000, refund=refund, status="partially_refunded")
    settlement = make_settlement(
        gross=1_000_000,
        refund_adjustment=refund,
        netted_refund_payment_ids=["PAY-89001"],
    )
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    output = engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    result = result_for(output, "ORD-10001")

    assert result.status is ReconciliationStatus.MATCHED
    assert result.variance_paisa == 0
    assert "PARTIAL_REFUND" in [c.value for c in result.reason_codes]
    assert len(result.adjustments) == 1
    adjustment = result.adjustments[0]
    assert adjustment.adjustment_type is AdjustmentType.PARTIAL_REFUND
    assert adjustment.amount_paisa == refund
    assert adjustment.related_payment == "PAY-89001"
    assert adjustment.evidence, "an adjustment must cite its source records"


def test_refund_netted_into_an_unrelated_payout_does_not_orphan_the_refunded_order(
    engine,
):
    """The core netting guarantee.

    Order A settles cleanly and is refunded later. The claw-back is netted
    inside order B's payout. A must stay MATCHED (its own settlement is intact)
    and B must stay MATCHED (its shortfall is explained by an AdjustmentRecord
    naming A). Neither may be reported as missing money.
    """
    refund = 300_000
    order_a = make_order("ORD-10001", "PAY-89001", "INV-10001", gross=1_000_000,
                         refund=refund, status="refunded")
    order_b = make_order("ORD-10002", "PAY-89002", "INV-10002", gross=2_000_000)

    settlement_a = make_settlement("SET-10001", ["PAY-89001"], gross=1_000_000)
    settlement_b = make_settlement(
        "SET-10002",
        ["PAY-89002"],
        gross=2_000_000,
        refund_adjustment=refund,
        netted_refund_payment_ids=["PAY-89001"],
    )
    credits = [
        make_bank_credit("BANK-77001", settlement_a.net_amount_paisa,
                         "RZP SET-10001", "SET-10001"),
        make_bank_credit("BANK-77002", settlement_b.net_amount_paisa,
                         "RZP SET-10002", "SET-10002"),
    ]
    invoices = [make_invoice("INV-10001", total=1_000_000),
                make_invoice("INV-10002", total=2_000_000)]
    output = engine.run(
        make_dataset([order_a, order_b], [settlement_a, settlement_b], credits, invoices)
    )

    a = result_for(output, "ORD-10001")
    b = result_for(output, "ORD-10002")

    assert a.status is ReconciliationStatus.MATCHED
    assert a.variance_paisa == 0

    assert b.status is ReconciliationStatus.MATCHED
    assert b.variance_paisa == 0
    assert "REFUND_NETTED" in [c.value for c in b.reason_codes]

    adjustment = b.adjustments[0]
    assert adjustment.adjustment_type is AdjustmentType.REFUND_NETTING
    assert adjustment.related_payment == "PAY-89001"
    assert adjustment.related_settlement == "SET-10002"
    assert adjustment.amount_paisa == refund


def test_chargeback_forces_review_and_records_the_reversal(engine):
    order = make_order(gross=1_000_000, status="chargeback")
    settlement = make_settlement(gross=1_000_000)
    net = settlement.net_amount_paisa
    rows = [
        make_bank_credit(amount=net),
        make_bank_debit(amount=net, transaction_date=SETTLE_DATE + timedelta(days=4)),
    ]
    result = result_for(
        engine.run(make_dataset([order], [settlement], rows, [make_invoice()])),
        "ORD-10001",
    )
    assert result.status is ReconciliationStatus.REVIEW_REQUIRED
    assert "CHARGEBACK" in [c.value for c in result.reason_codes]
    assert any(
        a.adjustment_type is AdjustmentType.CHARGEBACK for a in result.adjustments
    )
    # The cash arrived and left again, so retained value is zero and the full
    # payout is exposure. Reporting this as settled with zero variance would
    # hide a real loss on the exception desk.
    assert result.actual_amount_paisa == 0
    assert result.variance_paisa == -net
    assert result.unexplained_value_paisa == net


# --- 10. missing settlement ----------------------------------------------
def test_missing_settlement_is_an_honest_exception(engine):
    order = make_order(gross=1_000_000)
    output = engine.run(make_dataset([order], [], [], [make_invoice()]))
    result = result_for(output, "ORD-10001")

    assert result.status is ReconciliationStatus.EXCEPTION
    assert "MISSING_SETTLEMENT" in [c.value for c in result.reason_codes]
    assert result.confidence == 0.0
    assert result.confidence_method.value == "NOT_ESTABLISHED"
    assert result.settlement_ids == []
    # The exception still explains itself and cites real records.
    assert result.evidence
    assert any(e.record_id == "ORD-10001" for e in result.evidence)
    assert result.unexplained_value_paisa == result.expected_amount_paisa


def test_missing_bank_credit_is_a_partial_match_not_a_match(engine):
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    result = result_for(
        engine.run(make_dataset([order], [settlement], [], [make_invoice()])),
        "ORD-10001",
    )
    assert result.status is ReconciliationStatus.PARTIAL_MATCH
    assert "MISSING_BANK_TRANSACTION" in [c.value for c in result.reason_codes]
    # The settlement arithmetic is still proved, so the invariant confidence holds.
    assert result.variance_paisa == 0


# --- 11. unknown bank credit ---------------------------------------------
def test_unknown_bank_credit_becomes_its_own_exception(engine):
    stray = make_bank_credit(
        "BANK-99001",
        amount=8_420_000,
        description="NEFT CR-HDFC0000123-VENDOR REFUND-9928371",
        reference="",
    )
    output = engine.run(make_dataset([], [], [stray], []))
    assert len(output.results) == 1
    result = output.results[0]
    assert result.status is ReconciliationStatus.EXCEPTION
    assert [c.value for c in result.reason_codes] == ["UNKNOWN_BANK_CREDIT"]
    assert result.actual_amount_paisa == 8_420_000
    assert result.unexplained_value_paisa == 8_420_000
    assert result.confidence == 0.0
    assert result.bank_transaction_ids == ["BANK-99001"]


def test_unknown_credit_is_never_attached_to_a_plausible_nearby_order(engine):
    """A same-day credit of a DIFFERENT amount must not be absorbed into an order."""
    order = make_order(gross=1_000_000)
    settlement = make_settlement(gross=1_000_000)
    correct = make_bank_credit("BANK-77001", settlement.net_amount_paisa)
    stray = make_bank_credit(
        "BANK-77009",
        amount=555_555,
        description="IMPS INWARD 883712 MISC CREDIT",
        reference="",
    )
    output = engine.run(
        make_dataset([order], [settlement], [correct, stray], [make_invoice()])
    )
    matched = result_for(output, "ORD-10001")
    assert matched.status is ReconciliationStatus.MATCHED
    assert matched.bank_transaction_ids == ["BANK-77001"]

    orphan = next(r for r in output.results if r.order_id is None)
    assert orphan.status is ReconciliationStatus.EXCEPTION
    assert orphan.bank_transaction_ids == ["BANK-77009"]


def test_engine_never_returns_a_residual_without_a_reason_code(engine):
    """Structural guarantee: no unexplained outcome may leave the engine."""
    order_missing = make_order("ORD-10001", "PAY-89001", "INV-10001", gross=500_000)
    order_ok = make_order("ORD-10002", "PAY-89002", "INV-10002", gross=700_000)
    settlement = make_settlement("SET-10002", ["PAY-89002"], gross=700_000)
    credit = make_bank_credit("BANK-77002", settlement.net_amount_paisa,
                              "RZP SET-10002", "SET-10002")
    stray = make_bank_credit("BANK-77003", 12_345, "CASH DEPOSIT BRANCH 2291", "")
    output = engine.run(
        make_dataset(
            [order_missing, order_ok],
            [settlement],
            [credit, stray],
            [make_invoice("INV-10001", total=500_000),
             make_invoice("INV-10002", total=700_000)],
        )
    )
    for result in output.results:
        if result.status is not ReconciliationStatus.MATCHED:
            assert result.reason_codes, (
                f"{result.reconciliation_id} is {result.status} with no reason code"
            )
            assert result.evidence, (
                f"{result.reconciliation_id} is {result.status} with no evidence"
            )
