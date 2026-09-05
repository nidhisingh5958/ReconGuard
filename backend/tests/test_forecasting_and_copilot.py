"""Cash forecasting and the grounded copilot."""

from __future__ import annotations

from datetime import date, timedelta

from app.services.ai.copilot_qa import (
    INTENT_ARBITRATION,
    INTENT_COUNTERPARTY,
    INTENT_EXCEPTIONS,
    INTENT_EXPLAIN,
    INTENT_JOURNAL,
    INTENT_METRICS,
    INTENT_REASON,
    INTENT_UNEXPLAINED,
    INTENT_UNKNOWN,
    classify_intent,
)
from app.services.forecasting.forecaster import (
    DailyObservation,
    SettlementCycleForecaster,
    backtest,
)
from app.services.forecasting.interfaces import NoForecaster

START = date(2026, 6, 1)


def steady_history(days: int = 90, amount: int = 200_000_00):
    """Perfectly flat inflow. Any sane band must cover all of it."""
    return [DailyObservation(START + timedelta(days=i), amount) for i in range(days)]


def varied_history(days: int = 90):
    """Deterministic sawtooth: wide but bounded, so the band should hold."""
    return [
        DailyObservation(START + timedelta(days=i), 100_000_00 + (i % 20) * 5_000_00)
        for i in range(days)
    ]


# --- backtesting ----------------------------------------------------------
def test_confidence_is_measured_on_held_out_days_not_asserted():
    report = backtest(steady_history())
    assert report.usable
    assert report.train_days + report.test_days == 90
    assert report.coverage == 1.0
    assert report.hits == report.test_days
    assert "held-out" in report.note


def test_a_bounded_but_variable_series_is_still_covered():
    report = backtest(varied_history())
    assert report.usable
    assert report.coverage >= 0.7


def test_too_little_history_reports_itself_as_unusable():
    report = backtest(steady_history(days=4))
    assert not report.usable
    assert report.coverage == 0.0
    assert "at least" in report.note


def test_an_erratic_series_produces_an_honestly_low_coverage():
    """A method that does not work must say so rather than report a number."""
    history = [
        DailyObservation(START + timedelta(days=i), 1_000_00 if i < 60 else 900_000_00)
        for i in range(90)
    ]
    report = backtest(history)
    assert report.usable
    assert report.coverage == 0.0, "held-out days sit far outside the fitted band"


# --- forecasting ----------------------------------------------------------
def test_committed_lines_carry_exact_amounts_and_cite_their_settlement():
    forecaster = SettlementCycleForecaster(expected_lag_days=2)
    committed = [(START + timedelta(days=89), 555_555, ["SET-10291"])]
    result = forecaster.forecast(10, steady_history(), committed=committed)

    dated = [p for p in result.points if p.committed_paisa]
    assert len(dated) == 1
    assert dated[0].committed_paisa == 555_555
    assert dated[0].source_records == ["SET-10291"]
    assert result.committed_total_paisa == 555_555


def test_the_band_always_contains_the_expected_value():
    result = SettlementCycleForecaster().forecast(14, varied_history())
    for point in result.points:
        assert point.low_paisa <= point.expected_inflow_paisa <= point.high_paisa


def test_a_forecast_with_no_usable_history_projects_nothing():
    result = SettlementCycleForecaster().forecast(7, steady_history(days=3))
    assert result.projected_total_paisa == 0
    assert all(p.confidence == 0.0 for p in result.points)
    assert not result.backtest.usable


def test_committed_lines_beyond_the_horizon_are_excluded():
    forecaster = SettlementCycleForecaster(expected_lag_days=2)
    committed = [(START + timedelta(days=200), 999_999, ["SET-1"])]
    result = forecaster.forecast(5, steady_history(), committed=committed)
    assert result.committed_total_paisa == 0


def test_the_horizon_length_is_respected():
    result = SettlementCycleForecaster().forecast(21, steady_history())
    assert len(result.points) == 21


def test_the_no_op_forecaster_returns_nothing_rather_than_a_guess():
    assert NoForecaster().forecast(30, []) == []


def test_forecast_output_labels_its_method_and_never_claims_to_be_proved():
    result = SettlementCycleForecaster().forecast(7, varied_history())
    payload = result.to_dict()
    assert payload["method"] == "EMPIRICAL_DAILY_DECILE_BAND"
    assert payload["backtest"]["usable"] is True
    for point in payload["points"]:
        assert point["confidence"] <= 1.0
        assert point["basis"]


# --- copilot intent routing ----------------------------------------------
def test_intents_route_deterministically():
    cases = [
        ("Why was REC-00001 matched?", INTENT_EXPLAIN),
        ("Explain ORD-10001", INTENT_EXPLAIN),
        ("What are the biggest exceptions?", INTENT_EXCEPTIONS),
        ("What is the match rate for this run?", INTENT_METRICS),
        ("How fast did it process?", INTENT_METRICS),
        ("How much is unexplained?", INTENT_UNEXPLAINED),
        ("Which customer has the most at stake?", INTENT_COUNTERPARTY),
        ("Who owes us the most?", INTENT_COUNTERPARTY),
        ("Give me the reason code breakdown", INTENT_REASON),
        ("What did the arbitrator propose?", INTENT_ARBITRATION),
        ("What journal entries are pending?", INTENT_JOURNAL),
        ("What is the weather in Mumbai?", INTENT_UNKNOWN),
    ]
    failures = [
        f"{q!r} -> {classify_intent(q)}, expected {expected}"
        for q, expected in cases
        if classify_intent(q) != expected
    ]
    assert not failures, "\n".join(failures)


def test_intent_routing_is_stable_regardless_of_case_and_spacing():
    assert classify_intent("  WHAT IS THE MATCH RATE?  ") == INTENT_METRICS
    assert classify_intent("why was rec-00001 matched") == INTENT_EXPLAIN
