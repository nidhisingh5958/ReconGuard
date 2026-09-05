"""Deterministic fee and tax computation.

Every number produced here is reconstructible from the source gross amount and
the active AccountingConfig. Nothing is estimated, inferred or predicted. An
LLM is never involved: these are arithmetic identities.

Rule catalogue used by this module:
    RULE-FEE-001  gateway fee     = gross x gateway_fee_bps / 10000
    RULE-TAX-001  GST on fee      = gateway_fee x gst_on_fee_bps / 10000
    RULE-TAX-002  TDS             = gross x tds_bps / 10000
    RULE-ADJ-001  refund netting  = sum of refunds netted inside the payout
    RULE-NET-001  net settlement  = gross - fee - gst - tds - refunds + adj
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from app.core.config import AccountingConfig
from app.core.money import apply_rate_bps
from app.domain.reconciliation import CalculationLine

RULE_GATEWAY_FEE = "RULE-FEE-001"
RULE_GST_ON_FEE = "RULE-TAX-001"
RULE_TDS = "RULE-TAX-002"
RULE_REFUND_NETTING = "RULE-ADJ-001"
RULE_NET_SETTLEMENT = "RULE-NET-001"


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """The full deterministic reconstruction of a settlement payout."""

    gross_amount_paisa: int
    gateway_fee_paisa: int
    gst_on_fee_paisa: int
    tds_paisa: int
    refund_netting_paisa: int
    other_adjustments_paisa: int
    net_amount_paisa: int
    lines: List[CalculationLine] = field(default_factory=list)

    @property
    def total_deductions_paisa(self) -> int:
        return (
            self.gateway_fee_paisa
            + self.gst_on_fee_paisa
            + self.tds_paisa
            + self.refund_netting_paisa
        )

    def equation(self) -> str:
        """Human-readable arithmetic with the real numbers substituted."""
        parts = [
            str(self.gross_amount_paisa),
            f"- {self.gateway_fee_paisa}",
            f"- {self.gst_on_fee_paisa}",
            f"- {self.tds_paisa}",
        ]
        if self.refund_netting_paisa:
            parts.append(f"- {self.refund_netting_paisa}")
        if self.other_adjustments_paisa:
            sign = "+" if self.other_adjustments_paisa > 0 else "-"
            parts.append(f"{sign} {abs(self.other_adjustments_paisa)}")
        return f"{' '.join(parts)} = {self.net_amount_paisa}"

    def to_dict(self) -> dict:
        return {
            "gross_amount_paisa": self.gross_amount_paisa,
            "gateway_fee_paisa": self.gateway_fee_paisa,
            "gst_on_fee_paisa": self.gst_on_fee_paisa,
            "tds_paisa": self.tds_paisa,
            "refund_netting_paisa": self.refund_netting_paisa,
            "other_adjustments_paisa": self.other_adjustments_paisa,
            "net_amount_paisa": self.net_amount_paisa,
            "equation": self.equation(),
            "lines": [line.to_dict() for line in self.lines],
        }


def compute_gateway_fee(gross_amount_paisa: int, config: AccountingConfig) -> int:
    return apply_rate_bps(gross_amount_paisa, config.gateway_fee_bps)


def compute_gst_on_fee(gateway_fee_paisa: int, config: AccountingConfig) -> int:
    """GST is levied on the gateway fee, not on the gross transaction value."""
    return apply_rate_bps(gateway_fee_paisa, config.gst_on_fee_bps)


def compute_tds(gross_amount_paisa: int, config: AccountingConfig) -> int:
    """TDS is withheld on the gross value. The rate is configuration, not a constant."""
    return apply_rate_bps(gross_amount_paisa, config.tds_bps)


def compute_fee_breakdown(
    gross_amount_paisa: int,
    config: AccountingConfig,
    refund_netting_paisa: int = 0,
    other_adjustments_paisa: int = 0,
) -> FeeBreakdown:
    """Reconstruct the expected payout for a gross amount, showing all work."""
    gateway_fee = compute_gateway_fee(gross_amount_paisa, config)
    gst = compute_gst_on_fee(gateway_fee, config)
    tds = compute_tds(gross_amount_paisa, config)
    net = (
        gross_amount_paisa
        - gateway_fee
        - gst
        - tds
        - refund_netting_paisa
        + other_adjustments_paisa
    )

    lines = [
        CalculationLine(
            label="Gateway fee",
            expression=(
                f"{gross_amount_paisa} x {config.gateway_fee_bps}/10000 "
                f"= {gateway_fee}"
            ),
            result_paisa=gateway_fee,
            rule_id=RULE_GATEWAY_FEE,
        ),
        CalculationLine(
            label="GST on gateway fee",
            expression=f"{gateway_fee} x {config.gst_on_fee_bps}/10000 = {gst}",
            result_paisa=gst,
            rule_id=RULE_GST_ON_FEE,
        ),
        CalculationLine(
            label="TDS withheld",
            expression=f"{gross_amount_paisa} x {config.tds_bps}/10000 = {tds}",
            result_paisa=tds,
            rule_id=RULE_TDS,
        ),
    ]
    if refund_netting_paisa:
        lines.append(
            CalculationLine(
                label="Refunds netted in payout",
                expression=f"netted refunds = {refund_netting_paisa}",
                result_paisa=refund_netting_paisa,
                rule_id=RULE_REFUND_NETTING,
            )
        )

    breakdown = FeeBreakdown(
        gross_amount_paisa=gross_amount_paisa,
        gateway_fee_paisa=gateway_fee,
        gst_on_fee_paisa=gst,
        tds_paisa=tds,
        refund_netting_paisa=refund_netting_paisa,
        other_adjustments_paisa=other_adjustments_paisa,
        net_amount_paisa=net,
        lines=lines,
    )
    lines.append(
        CalculationLine(
            label="Expected net settlement",
            expression=breakdown.equation(),
            result_paisa=net,
            rule_id=RULE_NET_SETTLEMENT,
        )
    )
    return breakdown
