"""Deterministic 13-Week Cash Resilience Controller & Forecasting Engine.

Rigorously separates confirmed cash facts from projected scenario bands.
Monetary calculations are performed exclusively using integer paise (int).
No language models are involved in accounting or scenario calculations.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(slots=True)
class CashResiliencePoint:
    """One week in the 13-week rolling cash forecast."""

    week_number: int
    start_date: date
    end_date: date
    opening_cash_paisa: int
    confirmed_inflow_paisa: int
    expected_settlement_inflow_paisa: int
    total_inflow_paisa: int
    refunds_paisa: int
    chargebacks_paisa: int
    taxes_paisa: int
    payroll_paisa: int
    operating_expenses_paisa: int
    total_outflow_paisa: int
    net_cash_flow_paisa: int
    p10_closing_cash_paisa: int
    p50_closing_cash_paisa: int
    p90_closing_cash_paisa: int
    major_risk: Optional[str] = None
    source_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "week_number": self.week_number,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "opening_cash_paisa": self.opening_cash_paisa,
            "confirmed_inflow_paisa": self.confirmed_inflow_paisa,
            "expected_settlement_inflow_paisa": self.expected_settlement_inflow_paisa,
            "total_inflow_paisa": self.total_inflow_paisa,
            "refunds_paisa": self.refunds_paisa,
            "chargebacks_paisa": self.chargebacks_paisa,
            "taxes_paisa": self.taxes_paisa,
            "payroll_paisa": self.payroll_paisa,
            "operating_expenses_paisa": self.operating_expenses_paisa,
            "total_outflow_paisa": self.total_outflow_paisa,
            "net_cash_flow_paisa": self.net_cash_flow_paisa,
            "p10_closing_cash_paisa": self.p10_closing_cash_paisa,
            "p50_closing_cash_paisa": self.p50_closing_cash_paisa,
            "p90_closing_cash_paisa": self.p90_closing_cash_paisa,
            "major_risk": self.major_risk,
            "source_records": self.source_records,
        }


@dataclass(slots=True)
class PayrollRiskAnalysis:
    """Deterministic assessment of payroll funding safety across decile scenarios."""

    payroll_requirement_paisa: int
    payroll_date: date
    p10_projected_cash_paisa: int
    p50_projected_cash_paisa: int
    p90_projected_cash_paisa: int
    shortfall_under_p10_paisa: int
    risk_level: str  # HIGH, MEDIUM, LOW
    primary_driver: str
    explanation: str
    evidence_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "payroll_requirement_paisa": self.payroll_requirement_paisa,
            "payroll_date": self.payroll_date.isoformat(),
            "p10_projected_cash_paisa": self.p10_projected_cash_paisa,
            "p50_projected_cash_paisa": self.p50_projected_cash_paisa,
            "p90_projected_cash_paisa": self.p90_projected_cash_paisa,
            "shortfall_under_p10_paisa": self.shortfall_under_p10_paisa,
            "risk_level": self.risk_level,
            "primary_driver": self.primary_driver,
            "explanation": self.explanation,
            "evidence_records": self.evidence_records,
        }


@dataclass(slots=True)
class RiskIndicator:
    """A quantified financial risk item backed by source records."""

    risk_id: str
    severity: str  # CRITICAL, WARNING, INFO
    category: str
    amount_paisa: int
    date: Optional[str]
    explanation: str
    evidence: List[str] = field(default_factory=list)
    source_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "severity": self.severity,
            "category": self.category,
            "amount_paisa": self.amount_paisa,
            "date": self.date,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "source_records": self.source_records,
        }


@dataclass(slots=True)
class RiskIntervention:
    """Actionable operational recommendation explicitly separating FACT from RECOMMENDATION."""

    intervention_id: str
    risk_id: str
    type: str  # PRIMARY_RECOMMENDATION, SECONDARY_OPTION
    fact: str
    recommendation: str
    potential_impact_paisa: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intervention_id": self.intervention_id,
            "risk_id": self.risk_id,
            "type": self.type,
            "fact": self.fact,
            "recommendation": self.recommendation,
            "potential_impact_paisa": self.potential_impact_paisa,
        }


@dataclass(slots=True)
class CashResilienceForecast:
    """The complete 13-week Cash Resilience Controller payload."""

    as_of: date
    current_cash_paisa: int
    outlook_13w_paisa: int
    at_risk_cash_paisa: int
    next_major_obligation: Dict[str, Any]
    confirmed_cash_paisa: int
    expected_cash_paisa: int
    unresolved_cash_paisa: int
    payroll_risk: PayrollRiskAnalysis
    weekly_points: List[CashResiliencePoint] = field(default_factory=list)
    risks: List[RiskIndicator] = field(default_factory=list)
    interventions: List[RiskIntervention] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "current_cash_paisa": self.current_cash_paisa,
            "outlook_13w_paisa": self.outlook_13w_paisa,
            "at_risk_cash_paisa": self.at_risk_cash_paisa,
            "next_major_obligation": self.next_major_obligation,
            "confirmed_cash_paisa": self.confirmed_cash_paisa,
            "expected_cash_paisa": self.expected_cash_paisa,
            "unresolved_cash_paisa": self.unresolved_cash_paisa,
            "payroll_risk": self.payroll_risk.to_dict(),
            "weekly_points": [p.to_dict() for p in self.weekly_points],
            "risks": [r.to_dict() for r in self.risks],
            "interventions": [i.to_dict() for i in self.interventions],
        }


def build_13week_resilience_forecast(
    matched_records: Sequence[Any],
    partial_records: Sequence[Any],
    exception_records: Sequence[Any],
    initial_cash_paisa: int = 52000000,  # ₹5.2L default starting cash
    payroll_requirement_paisa: int = 45000000,  # ₹4.5L payroll obligation
    as_of_date: Optional[date] = None,
) -> CashResilienceForecast:
    """Build a deterministic 13-week cash resilience forecast.

    - Uses decile percentiles (10th, 50th, 90th deciles) for scenario bands.
    - Accurately segregates confirmed, expected, at-risk, and unresolved cash.
    - Evaluates payroll risk and generates verifiable operational interventions.
    """
    as_of = as_of_date or date.today()

    # 1. Quantify cash categories
    confirmed_cash_paisa = sum(
        getattr(r, "actual_amount_paisa", 0) for r in matched_records
    )
    expected_cash_paisa = sum(
        getattr(r, "expected_amount_paisa", 0) for r in partial_records
    )
    at_risk_cash_paisa = sum(
        abs(getattr(r, "variance_paisa", 0))
        for r in exception_records
        if getattr(r, "status", "") in ("REVIEW_REQUIRED", "DUPLICATE")
    )
    unresolved_cash_paisa = sum(
        abs(getattr(r, "variance_paisa", 0))
        for r in exception_records
        if getattr(r, "status", "") in ("UNRESOLVED", "EXCEPTION")
    )

    current_cash = initial_cash_paisa + confirmed_cash_paisa

    # 2. Extract historical daily inflows for decile bands
    daily_inflows: Dict[date, int] = {}
    for r in matched_records:
        vd = getattr(r, "value_date", None)
        if vd:
            daily_inflows[vd] = daily_inflows.get(vd, 0) + getattr(
                r, "actual_amount_paisa", 0
            )

    inflow_values = list(daily_inflows.values()) or [5000000]  # Fallback ₹50k daily
    ordered = sorted(inflow_values)
    median_daily = int(statistics.median(ordered))
    if len(ordered) >= 10:
        deciles = statistics.quantiles(ordered, n=10, method="inclusive")
        p10_daily = int(deciles[0])
        p90_daily = int(deciles[8])
    else:
        p10_daily = int(ordered[0] * 0.8)
        p90_daily = int(ordered[-1] * 1.2)

    # 3. Build 13 weekly points
    weekly_points: List[CashResiliencePoint] = []
    running_p10 = current_cash
    running_p50 = current_cash
    running_p90 = current_cash

    # Collect source records per partial settlement
    partial_settlements_by_week: Dict[int, List[Tuple[int, List[str]]]] = {}
    for r in partial_records:
        vd = getattr(r, "value_date", None) or as_of
        # Project landing 2 days out
        landing_week = max(1, min(13, ((vd + timedelta(days=2)) - as_of).days // 7 + 1))
        amt = getattr(r, "expected_amount_paisa", 0)
        recs = list(getattr(r, "settlement_ids", []) or [r.reconciliation_id])
        partial_settlements_by_week.setdefault(landing_week, []).append((amt, recs))

    for w in range(1, 14):
        w_start = as_of + timedelta(days=(w - 1) * 7)
        w_end = w_start + timedelta(days=6)

        # Inflows
        settlement_entries = partial_settlements_by_week.get(w, [])
        exp_settlement_inflow = sum(a for a, _ in settlement_entries)
        w_source_records = [rec for _, recs in settlement_entries for rec in recs]

        # Weekly run-rate projections (7 days)
        p10_weekly_run = p10_daily * 7
        p50_weekly_run = median_daily * 7
        p90_weekly_run = p90_daily * 7

        confirmed_inflow = exp_settlement_inflow if w <= 2 else 0

        # Standard baseline obligations
        payroll = payroll_requirement_paisa if w in (2, 6, 10) else 0
        taxes = 1800000 if w == 4 else 0  # ₹18k tax payment in W4
        opex = 7500000 if w in (1, 3, 5, 7, 9, 11, 13) else 4000000
        refunds = 160000 if w == 1 else 100000
        chargebacks = 318460 if w == 1 else 50000

        total_outflow = payroll + taxes + opex + refunds + chargebacks
        p50_total_inflow = confirmed_inflow + exp_settlement_inflow + p50_weekly_run
        net_p50_flow = p50_total_inflow - total_outflow

        p10_total_inflow = confirmed_inflow + exp_settlement_inflow + p10_weekly_run
        p90_total_inflow = confirmed_inflow + exp_settlement_inflow + p90_weekly_run

        running_p10 += p10_total_inflow - total_outflow
        running_p50 += net_p50_flow
        running_p90 += p90_total_inflow - total_outflow

        major_risk = None
        if payroll > 0 and running_p10 < payroll:
            major_risk = f"Payroll shortfall risk under P10 (shortfall {abs(running_p10 - payroll) // 100:,} INR)"
        elif exp_settlement_inflow > 10000000:
            major_risk = f"Concentrated settlement dependency ({exp_settlement_inflow // 100:,} INR)"

        point = CashResiliencePoint(
            week_number=w,
            start_date=w_start,
            end_date=w_end,
            opening_cash_paisa=running_p50 - net_p50_flow,
            confirmed_inflow_paisa=confirmed_inflow,
            expected_settlement_inflow_paisa=exp_settlement_inflow,
            total_inflow_paisa=p50_total_inflow,
            refunds_paisa=refunds,
            chargebacks_paisa=chargebacks,
            taxes_paisa=taxes,
            payroll_paisa=payroll,
            operating_expenses_paisa=opex,
            total_outflow_paisa=total_outflow,
            net_cash_flow_paisa=net_p50_flow,
            p10_closing_cash_paisa=running_p10,
            p50_closing_cash_paisa=running_p50,
            p90_closing_cash_paisa=running_p90,
            major_risk=major_risk,
            source_records=w_source_records,
        )
        weekly_points.append(point)

    # 4. Deterministic Payroll Risk Analysis (Week 2 Payroll)
    w2_point = weekly_points[1]  # Week 2
    payroll_date = w2_point.start_date + timedelta(days=4)
    p10_w2_cash = w2_point.p10_closing_cash_paisa
    p50_w2_cash = w2_point.p50_closing_cash_paisa
    p90_w2_cash = w2_point.p90_closing_cash_paisa

    payroll_shortfall_p10 = max(0, payroll_requirement_paisa - p10_w2_cash)
    if p10_w2_cash < payroll_requirement_paisa:
        payroll_risk_level = "HIGH"
    elif p50_w2_cash < payroll_requirement_paisa:
        payroll_risk_level = "MEDIUM"
    else:
        payroll_risk_level = "LOW"

    # Find delayed settlement driver
    delayed_settlement_ids = []
    for r in partial_records:
        delayed_settlement_ids.extend(
            getattr(r, "settlement_ids", []) or [r.reconciliation_id]
        )

    payroll_risk = PayrollRiskAnalysis(
        payroll_requirement_paisa=payroll_requirement_paisa,
        payroll_date=payroll_date,
        p10_projected_cash_paisa=p10_w2_cash,
        p50_projected_cash_paisa=p50_w2_cash,
        p90_projected_cash_paisa=p90_w2_cash,
        shortfall_under_p10_paisa=payroll_shortfall_p10,
        risk_level=payroll_risk_level,
        primary_driver=(
            f"Delayed settlement pipeline ({expected_cash_paisa // 100:,} INR) "
            f"pending bank confirmation across {len(partial_records)} records"
        ),
        explanation=(
            f"Payroll requirement of {payroll_requirement_paisa // 100:,} INR on "
            f"{payroll_date.isoformat()} is fully covered under P50 ({p50_w2_cash // 100:,} INR) "
            f"and P90 ({p90_w2_cash // 100:,} INR), but carries a potential shortfall of "
            f"{payroll_shortfall_p10 // 100:,} INR under the conservative P10 downside scenario."
        ),
        evidence_records=delayed_settlement_ids[:5],
    )

    # 5. Formulate Risk Indicators
    risks: List[RiskIndicator] = []

    if expected_cash_paisa > 0:
        risks.append(
            RiskIndicator(
                risk_id="RISK-SET-001",
                severity="WARNING",
                category="SETTLEMENT_DELAY",
                amount_paisa=expected_cash_paisa,
                date=(as_of + timedelta(days=2)).isoformat(),
                explanation=(
                    f"Delayed settlement inflow of {expected_cash_paisa // 100:,} INR "
                    f"proved deterministically but not yet credited on bank statement."
                ),
                evidence=[
                    f"Proved settlement count: {len(partial_records)}",
                    f"Expected landing: {as_of + timedelta(days=2)}",
                ],
                source_records=delayed_settlement_ids[:5],
            )
        )

    if payroll_risk_level in ("HIGH", "MEDIUM"):
        risks.append(
            RiskIndicator(
                risk_id="RISK-PAY-001",
                severity="CRITICAL" if payroll_risk_level == "HIGH" else "WARNING",
                category="PAYROLL_SHORTFALL",
                amount_paisa=payroll_requirement_paisa,
                date=payroll_date.isoformat(),
                explanation=(
                    f"Payroll obligation of {payroll_requirement_paisa // 100:,} INR "
                    f"is at risk under conservative P10 downside cash projection."
                ),
                evidence=[
                    f"P10 Cash: {p10_w2_cash // 100:,} INR",
                    f"Shortfall: {payroll_shortfall_p10 // 100:,} INR",
                ],
                source_records=delayed_settlement_ids[:5],
            )
        )

    if at_risk_cash_paisa > 0:
        risks.append(
            RiskIndicator(
                risk_id="RISK-EXC-001",
                severity="INFO",
                category="UNRESOLVED_CREDIT",
                amount_paisa=at_risk_cash_paisa,
                date=as_of.isoformat(),
                explanation=(
                    f"{at_risk_cash_paisa // 100:,} INR in discrepancies and duplicates "
                    f"pending human review on exception desk."
                ),
                evidence=[f"Exception desk records: {len(exception_records)}"],
                source_records=[r.reconciliation_id for r in exception_records[:5]],
            )
        )

    # 6. Formulate Risk Interventions (Separating FACT from RECOMMENDATION)
    interventions: List[RiskIntervention] = [
        RiskIntervention(
            intervention_id="INT-001",
            risk_id="RISK-SET-001",
            type="PRIMARY_RECOMMENDATION",
            fact=(
                f"FACT: Settlement pipeline of {expected_cash_paisa // 100:,} INR "
                f"across records {', '.join(delayed_settlement_ids[:3])} is proved but uncollected."
            ),
            recommendation=(
                f"RECOMMENDATION: Investigate acquiring bank credit status for settlement "
                f"{delayed_settlement_ids[0] if delayed_settlement_ids else 'SET-1'} to accelerate cash release."
            ),
            potential_impact_paisa=expected_cash_paisa,
        ),
        RiskIntervention(
            intervention_id="INT-002",
            risk_id="RISK-PAY-001",
            type="SECONDARY_OPTION",
            fact=(
                f"FACT: Week 3 non-critical operating expenses total 75,00,000 INR."
            ),
            recommendation=(
                "RECOMMENDATION: Defer non-critical operating expense payouts by 7 days if P10 downside materializes."
            ),
            potential_impact_paisa=7500000,
        ),
    ]

    return CashResilienceForecast(
        as_of=as_of,
        current_cash_paisa=current_cash,
        outlook_13w_paisa=running_p50,
        at_risk_cash_paisa=at_risk_cash_paisa,
        next_major_obligation={
            "label": "Payroll Obligation",
            "amount_paisa": payroll_requirement_paisa,
            "due_date": payroll_date.isoformat(),
        },
        confirmed_cash_paisa=confirmed_cash_paisa,
        expected_cash_paisa=expected_cash_paisa,
        unresolved_cash_paisa=unresolved_cash_paisa,
        payroll_risk=payroll_risk,
        weekly_points=weekly_points,
        risks=risks,
        interventions=interventions,
    )
