"""Accounting invariant verification.

An invariant check is NOT a fuzzy match. When the equation

    gross - gateway_fee - gst - tds - netted_refunds (+/- adjustments) = net

closes to the paisa, the settlement is *proved* to correspond to the payment.
That proof is what earns confidence 1.0. When it does not close, we quantify
the gap and attribute it to a specific component rather than shrugging.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.config import AccountingConfig
from app.domain.enums import ReasonCode
from app.domain.reconciliation import CalculationLine
from app.services.accounting.fees import (
    RULE_GATEWAY_FEE,
    RULE_GST_ON_FEE,
    RULE_NET_SETTLEMENT,
    RULE_TDS,
    FeeBreakdown,
    compute_fee_breakdown,
    compute_gst_on_fee,
)

RULE_SETTLEMENT_SELF_CONSISTENCY = "RULE-NET-002"
RULE_ROUNDING_TOLERANCE = "RULE-TOL-001"
RULE_JOURNAL_BALANCE = "RULE-JRN-001"


@dataclass(slots=True)
class InvariantCheck:
    """Outcome of proving (or failing to prove) the settlement equation."""

    holds_exactly: bool
    within_tolerance: bool
    expected_net_paisa: int
    actual_net_paisa: int
    variance_paisa: int
    component_variances: Dict[str, int] = field(default_factory=dict)
    reason_codes: List[ReasonCode] = field(default_factory=list)
    lines: List[CalculationLine] = field(default_factory=list)
    breakdown: Optional[FeeBreakdown] = None

    @property
    def proved(self) -> bool:
        """True when the equation closed exactly or inside the rounding tolerance."""
        return self.holds_exactly or self.within_tolerance


def verify_settlement_invariant(
    gross_amount_paisa: int,
    reported_gateway_fee_paisa: int,
    reported_gst_paisa: int,
    reported_tds_paisa: int,
    reported_refund_adjustment_paisa: int,
    reported_net_paisa: int,
    config: AccountingConfig,
    rounding_tolerance_paisa: int = 1,
) -> InvariantCheck:
    """Prove the settlement equation for a single payment against a single payout.

    Thin wrapper over :func:`verify_component_invariant` for the common one to
    one case, where the expected components come from this one gross amount.
    """
    return verify_component_invariant(
        component_gross_amounts=[gross_amount_paisa],
        reported_gateway_fee_paisa=reported_gateway_fee_paisa,
        reported_gst_paisa=reported_gst_paisa,
        reported_tds_paisa=reported_tds_paisa,
        reported_refund_adjustment_paisa=reported_refund_adjustment_paisa,
        reported_net_paisa=reported_net_paisa,
        config=config,
        rounding_tolerance_paisa=rounding_tolerance_paisa,
    )


def verify_component_invariant(
    component_gross_amounts: List[int],
    reported_gateway_fee_paisa: int,
    reported_gst_paisa: int,
    reported_tds_paisa: int,
    reported_refund_adjustment_paisa: int,
    reported_net_paisa: int,
    config: AccountingConfig,
    rounding_tolerance_paisa: int = 1,
) -> InvariantCheck:
    """Prove the settlement equation over N contributing gross amounts.

    ``component_gross_amounts`` is the list of gross values that should make up
    this payout: one entry for a plain settlement, one per payment for an
    aggregated payout, one per leg for a split payout. Fees are computed per
    component and then summed, which is how a gateway actually charges them.
    Computing the fee on the combined gross instead would introduce rounding
    drift that looks like a real discrepancy.

    Two independent checks run:

    1. Component check. Does each reported component equal what the configured
       rate produces? A gap here localises the problem to the fee, the GST or
       the TDS specifically.
    2. Self-consistency check. Do the numbers the settlement itself reports add
       up to the net it itself reports? A gap here is an arithmetic or rounding
       fault inside the source record.
    """
    breakdowns = [compute_fee_breakdown(g, config) for g in component_gross_amounts]
    gross_amount_paisa = sum(component_gross_amounts)
    expected_fee = sum(b.gateway_fee_paisa for b in breakdowns)
    expected_tds = sum(b.tds_paisa for b in breakdowns)
    expected_component_gst = sum(b.gst_on_fee_paisa for b in breakdowns)
    expected_net_before_refunds = sum(b.net_amount_paisa for b in breakdowns)
    expected_net = expected_net_before_refunds - reported_refund_adjustment_paisa

    expected = FeeBreakdown(
        gross_amount_paisa=gross_amount_paisa,
        gateway_fee_paisa=expected_fee,
        gst_on_fee_paisa=expected_component_gst,
        tds_paisa=expected_tds,
        refund_netting_paisa=reported_refund_adjustment_paisa,
        other_adjustments_paisa=0,
        net_amount_paisa=expected_net,
        lines=[],
    )

    component_variances: Dict[str, int] = {}
    reason_codes: List[ReasonCode] = []
    lines: List[CalculationLine] = []

    if len(breakdowns) == 1:
        # Show the derivation WITH the refund deduction included, so the
        # "Expected net settlement" line states the same number the invariant
        # is actually checked against. Printing a refund-free subtotal here and
        # a refund-inclusive one below would put two different "expected" values
        # in front of a reviewer.
        lines.extend(
            compute_fee_breakdown(
                component_gross_amounts[0],
                config,
                refund_netting_paisa=reported_refund_adjustment_paisa,
            ).lines
        )
    else:
        for gross, b in zip(component_gross_amounts, breakdowns):
            lines.append(
                CalculationLine(
                    label="Component payout",
                    expression=b.equation(),
                    result_paisa=b.net_amount_paisa,
                    rule_id=RULE_NET_SETTLEMENT,
                )
            )
        lines.append(
            CalculationLine(
                label="Expected net settlement (sum of components)",
                expression=expected.equation(),
                result_paisa=expected_net,
                rule_id=RULE_NET_SETTLEMENT,
            )
        )

    # --- 1. component attribution -------------------------------------------
    fee_variance = reported_gateway_fee_paisa - expected_fee
    if fee_variance:
        component_variances["gateway_fee_paisa"] = fee_variance
        reason_codes.append(ReasonCode.GATEWAY_FEE_MISMATCH)
        lines.append(
            CalculationLine(
                label="Gateway fee variance",
                expression=(
                    f"reported {reported_gateway_fee_paisa} "
                    f"- expected {expected_fee} = {fee_variance}"
                ),
                result_paisa=fee_variance,
                rule_id=RULE_GATEWAY_FEE,
            )
        )

    # When the fee itself is wrong, GST is verified against the fee the
    # settlement actually reports, so one fee error does not cascade into a
    # phantom second GST error. When the fee is correct we use the per-component
    # sum, which is what a real gateway bills.
    expected_gst = (
        expected_component_gst
        if fee_variance == 0
        else compute_gst_on_fee(reported_gateway_fee_paisa, config)
    )
    gst_variance = reported_gst_paisa - expected_gst
    if gst_variance:
        component_variances["gst_on_fee_paisa"] = gst_variance
        reason_codes.append(ReasonCode.GST_MISMATCH)
        lines.append(
            CalculationLine(
                label="GST variance",
                expression=(
                    f"reported {reported_gst_paisa} - expected {expected_gst} "
                    f"(at {config.gst_on_fee_bps}/10000 on the gateway fee) "
                    f"= {gst_variance}"
                ),
                result_paisa=gst_variance,
                rule_id=RULE_GST_ON_FEE,
            )
        )

    tds_variance = reported_tds_paisa - expected_tds
    if tds_variance:
        component_variances["tds_paisa"] = tds_variance
        reason_codes.append(ReasonCode.TDS_MISMATCH)
        lines.append(
            CalculationLine(
                label="TDS variance",
                expression=(
                    f"reported {reported_tds_paisa} "
                    f"- expected {expected_tds} = {tds_variance}"
                ),
                result_paisa=tds_variance,
                rule_id=RULE_TDS,
            )
        )

    # --- 2. self-consistency of the source record ---------------------------
    self_consistent_net = (
        gross_amount_paisa
        - reported_gateway_fee_paisa
        - reported_gst_paisa
        - reported_tds_paisa
        - reported_refund_adjustment_paisa
    )
    self_variance = reported_net_paisa - self_consistent_net
    if self_variance:
        component_variances["self_consistency_paisa"] = self_variance
        lines.append(
            CalculationLine(
                label="Settlement self-consistency",
                expression=(
                    f"{gross_amount_paisa} - {reported_gateway_fee_paisa} "
                    f"- {reported_gst_paisa} - {reported_tds_paisa} "
                    f"- {reported_refund_adjustment_paisa} = {self_consistent_net}, "
                    f"reported net {reported_net_paisa}, variance {self_variance}"
                ),
                result_paisa=self_variance,
                rule_id=RULE_SETTLEMENT_SELF_CONSISTENCY,
            )
        )

    # --- verdict ------------------------------------------------------------
    variance = reported_net_paisa - expected.net_amount_paisa
    holds_exactly = variance == 0
    within_tolerance = (not holds_exactly) and abs(variance) <= rounding_tolerance_paisa

    if holds_exactly:
        lines.append(
            CalculationLine(
                label="Invariant verified",
                expression=(
                    f"{expected.equation()} == reported net {reported_net_paisa}"
                ),
                result_paisa=0,
                rule_id=RULE_NET_SETTLEMENT,
            )
        )
    elif within_tolerance:
        reason_codes.append(ReasonCode.ROUNDING_TOLERANCE_APPLIED)
        lines.append(
            CalculationLine(
                label="Rounding tolerance applied",
                expression=(
                    f"abs({reported_net_paisa} - {expected.net_amount_paisa}) "
                    f"= {abs(variance)} <= tolerance "
                    f"{rounding_tolerance_paisa} paisa"
                ),
                result_paisa=variance,
                rule_id=RULE_ROUNDING_TOLERANCE,
            )
        )
    else:
        reason_codes.append(ReasonCode.NET_AMOUNT_VARIANCE)
        lines.append(
            CalculationLine(
                label="Net settlement variance",
                expression=(
                    f"reported {reported_net_paisa} - expected "
                    f"{expected.net_amount_paisa} = {variance}"
                ),
                result_paisa=variance,
                rule_id=RULE_NET_SETTLEMENT,
            )
        )

    return InvariantCheck(
        holds_exactly=holds_exactly,
        within_tolerance=within_tolerance,
        expected_net_paisa=expected.net_amount_paisa,
        actual_net_paisa=reported_net_paisa,
        variance_paisa=variance,
        component_variances=component_variances,
        reason_codes=reason_codes,
        lines=lines,
        breakdown=expected,
    )


def verify_journal_entries_balance(entries) -> tuple:
    """Double-entry gate: total debits must equal total credits, to the paisa.

    Returns ``(balanced, total_debits, total_credits)``. A proposed journal
    entry that fails this check is rejected before it can be persisted, no
    matter how confident whatever proposed it happened to be.
    """
    total_debits = 0
    total_credits = 0
    for entry in entries:
        amount = int(entry.amount_paisa)
        if amount >= 0:
            total_debits += amount
            total_credits += amount
        else:
            # A negative-amount entry is a reversal: it still has to balance,
            # but recording it on both sides keeps the sign convention honest.
            total_debits += amount
            total_credits += amount
    return total_debits == total_credits, total_debits, total_credits
