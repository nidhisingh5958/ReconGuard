"""Cash forecasting.

Two things are reported and they are kept rigorously apart, because a finance
team must always be able to tell an obligation from a guess:

**Committed pipeline** is not a forecast. Each line is a settlement whose
arithmetic the engine proved and whose credit has not been located. The amount
is exact and the evidence is a real settlement id. Only the *timing* is
projected, from the configured payout cycle.

**Projected inflow** is a forecast, and it is stated as a band rather than a
point. The band is the p10-p90 range of observed daily inflow, and the
confidence attached to it is not asserted - it is **backtested**: the method
is fitted on the earlier part of the observed history and scored on the later
part, and the reported confidence is the fraction of held-out days that actually
landed inside the band.

That means a low confidence here is informative rather than decorative. If the
history is too short or too erratic for the method to work, the number says so.
No language model is involved in any of this.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

METHOD_COMMITTED = "COMMITTED_PIPELINE"
METHOD_RUN_RATE = "EMPIRICAL_DAILY_DECILE_BAND"

MIN_HISTORY_DAYS = 8
MIN_BACKTEST_DAYS = 3
TRAIN_FRACTION = 0.7


@dataclass(slots=True)
class DailyObservation:
    """One day of confirmed inflow, read off reconciled records."""

    day: date
    amount_paisa: int


@dataclass(slots=True)
class ForecastPoint:
    value_date: date
    expected_inflow_paisa: int
    low_paisa: int
    high_paisa: int
    method: str
    confidence: float
    basis: str
    committed_paisa: int = 0
    projected_paisa: int = 0
    source_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value_date": self.value_date.isoformat(),
            "expected_inflow_paisa": self.expected_inflow_paisa,
            "low_paisa": self.low_paisa,
            "high_paisa": self.high_paisa,
            "committed_paisa": self.committed_paisa,
            "projected_paisa": self.projected_paisa,
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "basis": self.basis,
            "source_records": self.source_records,
        }


@dataclass(slots=True)
class BacktestReport:
    """How well the projection method did on held-out history."""

    train_days: int
    test_days: int
    hits: int
    coverage: float
    median_paisa: int
    low_paisa: int
    high_paisa: int
    usable: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "train_days": self.train_days,
            "test_days": self.test_days,
            "hits": self.hits,
            "coverage": round(self.coverage, 4),
            "median_paisa": self.median_paisa,
            "low_paisa": self.low_paisa,
            "high_paisa": self.high_paisa,
            "usable": self.usable,
            "note": self.note,
        }


@dataclass(slots=True)
class ForecastResult:
    points: List[ForecastPoint] = field(default_factory=list)
    backtest: Optional[BacktestReport] = None
    horizon_days: int = 0
    method: str = METHOD_RUN_RATE
    committed_total_paisa: int = 0
    projected_total_paisa: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "horizon_days": self.horizon_days,
            "method": self.method,
            "committed_total_paisa": self.committed_total_paisa,
            "projected_total_paisa": self.projected_total_paisa,
            "expected_total_paisa": (
                self.committed_total_paisa + self.projected_total_paisa
            ),
            "backtest": self.backtest.to_dict() if self.backtest else None,
            "points": [p.to_dict() for p in self.points],
        }


def _band(values: Sequence[int]) -> Tuple[int, int, int]:
    """Return ``(p10, median, p90)`` for a set of daily inflows.

    Deciles rather than quartiles. An interquartile band covers only about half
    the distribution by construction, which makes it a poor planning range for
    cash: a band you fall outside of every other day tells a treasurer nothing.
    p10-p90 targets roughly 80% coverage, and the backtest then reports whether
    that was actually achieved on held-out days rather than assuming it.
    """
    ordered = sorted(values)
    if not ordered:
        return 0, 0, 0
    median = int(statistics.median(ordered))
    if len(ordered) < 10:
        return ordered[0], median, ordered[-1]
    deciles = statistics.quantiles(ordered, n=10, method="inclusive")
    return int(deciles[0]), median, int(deciles[8])


def backtest(history: Sequence[DailyObservation]) -> BacktestReport:
    """Fit the band on early history, score it on the held-out remainder."""
    ordered = sorted(history, key=lambda o: o.day)
    if len(ordered) < MIN_HISTORY_DAYS:
        return BacktestReport(
            train_days=len(ordered),
            test_days=0,
            hits=0,
            coverage=0.0,
            median_paisa=0,
            low_paisa=0,
            high_paisa=0,
            usable=False,
            note=(
                f"only {len(ordered)} days of confirmed inflow observed; at least "
                f"{MIN_HISTORY_DAYS} are needed before a projection can be scored"
            ),
        )

    split = max(MIN_BACKTEST_DAYS, int(len(ordered) * TRAIN_FRACTION))
    train = ordered[:split]
    test = ordered[split:]
    if len(test) < MIN_BACKTEST_DAYS:
        split = len(ordered) - MIN_BACKTEST_DAYS
        train, test = ordered[:split], ordered[split:]

    low, median, high = _band([o.amount_paisa for o in train])
    hits = sum(1 for o in test if low <= o.amount_paisa <= high)
    coverage = hits / len(test) if test else 0.0

    return BacktestReport(
        train_days=len(train),
        test_days=len(test),
        hits=hits,
        coverage=coverage,
        median_paisa=median,
        low_paisa=low,
        high_paisa=high,
        usable=True,
        note=(
            f"band fitted on {len(train)} days, scored on {len(test)} held-out "
            f"days; {hits} of {len(test)} landed inside the band"
        ),
    )


class SettlementCycleForecaster:
    """Projects inflow from committed settlements plus a backtested run rate."""

    name = "settlement-cycle"

    def __init__(self, expected_lag_days: int = 2) -> None:
        self.expected_lag_days = expected_lag_days

    def forecast(
        self,
        horizon_days: int,
        history: Sequence[DailyObservation],
        committed: Optional[Sequence[Tuple[Optional[date], int, List[str]]]] = None,
        as_of: Optional[date] = None,
    ) -> ForecastResult:
        """Build a dated forecast.

        ``committed`` is ``(value_date, amount_paisa, source_records)`` per
        proved-but-uncollected settlement. Those amounts are exact; only their
        landing date is projected.
        """
        as_of = as_of or (
            max((o.day for o in history), default=date.today())
        )
        report = backtest(history)
        result = ForecastResult(
            horizon_days=horizon_days,
            method=METHOD_RUN_RATE,
            backtest=report,
        )

        # --- committed lines, bucketed by projected landing date ----------
        buckets: Dict[date, List[Tuple[int, List[str]]]] = {}
        for value_date, amount, records in committed or []:
            landing = (value_date or as_of) + timedelta(days=self.expected_lag_days)
            if landing <= as_of:
                landing = as_of + timedelta(days=1)
            if (landing - as_of).days > horizon_days:
                continue
            buckets.setdefault(landing, []).append((amount, records))

        for offset in range(1, horizon_days + 1):
            day = as_of + timedelta(days=offset)
            entries = buckets.get(day, [])
            committed_paisa = sum(a for a, _ in entries)
            records = sorted({r for _, rs in entries for r in rs})

            projected = report.median_paisa if report.usable else 0
            low = (report.low_paisa if report.usable else 0) + committed_paisa
            high = (report.high_paisa if report.usable else 0) + committed_paisa

            basis_parts = []
            if committed_paisa:
                basis_parts.append(
                    f"{len(entries)} proved settlement(s) awaiting cash, exact "
                    f"amounts"
                )
            if report.usable:
                basis_parts.append(
                    f"daily run-rate band from {report.train_days} observed days"
                )
            basis = "; ".join(basis_parts) or "no committed pipeline and no usable history"

            result.points.append(
                ForecastPoint(
                    value_date=day,
                    expected_inflow_paisa=committed_paisa + projected,
                    low_paisa=low,
                    high_paisa=high,
                    method=(
                        METHOD_COMMITTED
                        if committed_paisa and not report.usable
                        else METHOD_RUN_RATE
                    ),
                    confidence=report.coverage if report.usable else 0.0,
                    basis=basis,
                    committed_paisa=committed_paisa,
                    projected_paisa=projected,
                    source_records=records,
                )
            )

        result.committed_total_paisa = sum(p.committed_paisa for p in result.points)
        result.projected_total_paisa = sum(p.projected_paisa for p in result.points)
        return result
