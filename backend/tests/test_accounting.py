"""Accounting engine tests: fee, GST, TDS, net settlement, rounding.

This is the highest-value test module in the repository. Every number here is
independently hand-derivable, so a regression in the money layer fails loudly
rather than shifting a match rate by a fraction of a percent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config import AccountingConfig
from app.core.money import apply_rate_bps, format_inr, paisa_to_rupees, rupees_to_paisa
from app.services.accounting.fees import (
    compute_fee_breakdown,
    compute_gateway_fee,
    compute_gst_on_fee,
    compute_tds,
)
from app.services.accounting.invariants import (
    verify_component_invariant,
    verify_journal_entries_balance,
    verify_settlement_invariant,
)


# --- money primitives ----------------------------------------------------
def test_rupees_to_paisa_is_exact():
    assert rupees_to_paisa("1000.25") == 100_025
    assert rupees_to_paisa("0.01") == 1
    assert rupees_to_paisa(1000) == 100_000
    assert rupees_to_paisa(Decimal("99999.99")) == 9_999_999


def test_float_money_input_is_rejected():
    """0.1 + 0.2 != 0.3 in binary floating point, so floats are refused outright."""
    with pytest.raises(TypeError):
        rupees_to_paisa(1000.25)


def test_paisa_to_rupees_round_trips():
    assert paisa_to_rupees(100_025) == Decimal("1000.25")


def test_format_inr_uses_indian_grouping():
    assert format_inr(9_762_000) == "Rs.97,620.00"
    # Lakh/crore grouping: 2-2-3 above the thousands, not 3-3-3.
    assert format_inr(12_345_678_901) == "Rs.12,34,56,789.01"
    assert format_inr(10_000_000) == "Rs.1,00,000.00"
    assert format_inr(-100_025) == "-Rs.1,000.25"
    assert format_inr(0) == "Rs.0.00"


# --- 1. fee calculation --------------------------------------------------
def test_gateway_fee_is_two_percent_of_gross(accounting):
    # Rs.1,000.00 gross -> 2% -> Rs.20.00
    assert compute_gateway_fee(100_000, accounting) == 2_000


def test_gateway_fee_rounds_half_up_at_the_paisa(accounting):
    # 12345 paise x 2% = 246.9 paise -> 247
    assert compute_gateway_fee(12_345, accounting) == 247


def test_gateway_fee_rate_is_configuration_not_a_constant():
    assert compute_gateway_fee(100_000, AccountingConfig(gateway_fee_bps=250)) == 2_500


# --- 2. GST calculation --------------------------------------------------
def test_gst_is_levied_on_the_fee_not_the_gross(accounting):
    fee = compute_gateway_fee(100_000, accounting)
    assert compute_gst_on_fee(fee, accounting) == 360  # 18% of 2000
    # The distinction matters: 18% of gross would be 18000, not 360.
    assert compute_gst_on_fee(fee, accounting) != apply_rate_bps(100_000, 1800)


def test_gst_rounds_half_up(accounting):
    # 247 x 18% = 44.46 -> 44
    assert compute_gst_on_fee(247, accounting) == 44


# --- 3. TDS calculation --------------------------------------------------
def test_tds_is_computed_on_gross_at_the_configured_rate(accounting):
    assert compute_tds(100_000, accounting) == 100  # 0.10%


def test_tds_rate_is_configurable_end_to_end():
    """The spec worked example uses a 0.02% TDS rate; it must reproduce exactly."""
    cfg = AccountingConfig(tds_bps=2)
    breakdown = compute_fee_breakdown(100_000, cfg)
    assert breakdown.gateway_fee_paisa == 2_000
    assert breakdown.gst_on_fee_paisa == 360
    assert breakdown.tds_paisa == 20
    assert breakdown.net_amount_paisa == 97_620
    assert breakdown.equation() == "100000 - 2000 - 360 - 20 = 97620"


def test_zero_tds_rate_produces_no_withholding():
    assert compute_tds(100_000, AccountingConfig(tds_bps=0)) == 0


# --- 4. net settlement calculation ---------------------------------------
def test_net_settlement_equation(accounting):
    b = compute_fee_breakdown(100_000, accounting)
    assert b.net_amount_paisa == 100_000 - 2_000 - 360 - 100
    assert b.net_amount_paisa == 97_540
    assert b.total_deductions_paisa == 2_460


def test_net_settlement_subtracts_netted_refunds(accounting):
    b = compute_fee_breakdown(100_000, accounting, refund_netting_paisa=25_000)
    assert b.net_amount_paisa == 97_540 - 25_000
    assert "- 25000" in b.equation()


def test_breakdown_shows_its_work_with_rule_ids(accounting):
    b = compute_fee_breakdown(100_000, accounting)
    rules = {line.rule_id for line in b.lines}
    assert {"RULE-FEE-001", "RULE-TAX-001", "RULE-TAX-002", "RULE-NET-001"} <= rules
    assert any("100000 x 200/10000 = 2000" in l.expression for l in b.lines)


def test_invariant_closes_for_a_correct_settlement(accounting):
    check = verify_settlement_invariant(100_000, 2_000, 360, 100, 0, 97_540, accounting)
    assert check.holds_exactly
    assert check.proved
    assert check.variance_paisa == 0
    assert check.reason_codes == []


# --- 5. Rs.0.01 rounding -------------------------------------------------
def test_one_paisa_shortfall_is_absorbed_and_labelled(accounting):
    check = verify_settlement_invariant(100_000, 2_000, 360, 100, 0, 97_539, accounting)
    assert not check.holds_exactly
    assert check.within_tolerance
    assert check.proved
    assert check.variance_paisa == -1
    assert [c.value for c in check.reason_codes] == ["ROUNDING_TOLERANCE_APPLIED"]


def test_two_paisa_shortfall_exceeds_tolerance(accounting):
    check = verify_settlement_invariant(
        100_000, 2_000, 360, 100, 0, 97_538, accounting, rounding_tolerance_paisa=1
    )
    assert not check.proved
    assert check.variance_paisa == -2
    assert "NET_AMOUNT_VARIANCE" in [c.value for c in check.reason_codes]


def test_rounding_tolerance_is_configurable(accounting):
    check = verify_settlement_invariant(
        100_000, 2_000, 360, 100, 0, 97_538, accounting, rounding_tolerance_paisa=5
    )
    assert check.within_tolerance


# --- component attribution -----------------------------------------------
def test_tds_discrepancy_is_localised_to_tds(accounting):
    check = verify_settlement_invariant(
        100_000, 2_000, 360, 15_100, 0, 82_540, accounting
    )
    assert not check.proved
    assert check.component_variances["tds_paisa"] == 15_000
    assert "TDS_MISMATCH" in [c.value for c in check.reason_codes]


def test_gst_discrepancy_is_localised_to_gst(accounting):
    check = verify_settlement_invariant(
        100_000, 2_000, 2_860, 100, 0, 95_040, accounting
    )
    assert check.component_variances["gst_on_fee_paisa"] == 2_500
    assert "GST_MISMATCH" in [c.value for c in check.reason_codes]


def test_fee_error_does_not_cascade_into_a_phantom_gst_error(accounting):
    """A wrong fee with GST correct FOR that fee must report one fault, not two."""
    wrong_fee = 3_000
    gst_on_wrong_fee = compute_gst_on_fee(wrong_fee, accounting)  # 540
    check = verify_settlement_invariant(
        100_000, wrong_fee, gst_on_wrong_fee, 100, 0, 96_360, accounting
    )
    codes = [c.value for c in check.reason_codes]
    assert "GATEWAY_FEE_MISMATCH" in codes
    assert "GST_MISMATCH" not in codes


# --- aggregated / split component invariant ------------------------------
def test_component_invariant_sums_fees_per_payment(accounting):
    grosses = [123_400, 987_600, 55_500]
    parts = [compute_fee_breakdown(g, accounting) for g in grosses]
    check = verify_component_invariant(
        component_gross_amounts=grosses,
        reported_gateway_fee_paisa=sum(p.gateway_fee_paisa for p in parts),
        reported_gst_paisa=sum(p.gst_on_fee_paisa for p in parts),
        reported_tds_paisa=sum(p.tds_paisa for p in parts),
        reported_refund_adjustment_paisa=0,
        reported_net_paisa=sum(p.net_amount_paisa for p in parts),
        config=accounting,
    )
    assert check.holds_exactly
    assert check.expected_net_paisa == sum(p.net_amount_paisa for p in parts)


def test_fee_on_the_sum_differs_from_the_sum_of_fees(accounting):
    """Why per-component fees matter: rounding does not distribute over a sum.

    Charging 2% on each Rs.125.25 leg rounds 250.5 up three times (753 paise).
    Charging 2% on the Rs.375.75 total rounds 751.5 up once (752 paise). Using
    the wrong one would manufacture a 1 paisa variance on every aggregated
    payout, which is exactly the kind of phantom exception this system exists
    to avoid.
    """
    grosses = [12_525, 12_525, 12_525]
    per_component = sum(compute_gateway_fee(g, accounting) for g in grosses)
    on_the_total = compute_gateway_fee(sum(grosses), accounting)
    assert per_component == 753
    assert on_the_total == 752
    assert per_component != on_the_total


# --- journal entry balance gate ------------------------------------------
def test_journal_entries_must_balance():
    class Entry:
        def __init__(self, amount):
            self.amount_paisa = amount

    balanced, debits, credits = verify_journal_entries_balance(
        [Entry(50_000), Entry(25_000)]
    )
    assert balanced
    assert debits == credits == 75_000
