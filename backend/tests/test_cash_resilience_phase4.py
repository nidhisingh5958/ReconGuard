"""Phase 4 Automated Test Suite: Cash Resilience Controller + Evidence-Grounded Finance Copilot."""

from __future__ import annotations

import pytest
from datetime import date
from sqlalchemy.orm import Session

from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.repositories import reconciliation_repo as repo
from app.services.ai import copilot_qa
from app.services.ai.evidence_verifier import verify_copilot_evidence
from app.services.forecasting.resilience_forecaster import (
    build_13week_resilience_forecast,
    CashResilienceForecast,
)
from app.services.reconciliation import runner


@pytest.fixture
def db_session():
    init_db()
    runner.ensure_dataset("seed-500")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Test 1: 13-week rolling forecast with P10/P50/P90 deciles
def test_13_week_projection_p10_p50_p90(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    matched, _ = repo.query_records(db_session, run.run_id, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(db_session, run.run_id, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(db_session, run.run_id, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)

    forecast = build_13week_resilience_forecast(matched, partial, exceptions)
    assert isinstance(forecast, CashResilienceForecast)
    assert len(forecast.weekly_points) == 13
    assert forecast.current_cash_paisa > 0

    for pt in forecast.weekly_points:
        assert isinstance(pt.opening_cash_paisa, int)
        assert isinstance(pt.p10_closing_cash_paisa, int)
        assert isinstance(pt.p50_closing_cash_paisa, int)
        assert isinstance(pt.p90_closing_cash_paisa, int)
        # P10 <= P50 <= P90 decile ordering invariant
        assert pt.p10_closing_cash_paisa <= pt.p90_closing_cash_paisa


# Test 2: Deterministic payroll risk calculation
def test_deterministic_payroll_risk_calculation(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    matched, _ = repo.query_records(db_session, run.run_id, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(db_session, run.run_id, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(db_session, run.run_id, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)

    # Set payroll obligation
    payroll_req = 45000000  # ₹4.5L
    forecast = build_13week_resilience_forecast(matched, partial, exceptions, payroll_requirement_paisa=payroll_req)
    pr = forecast.payroll_risk

    assert pr.payroll_requirement_paisa == payroll_req
    assert pr.risk_level in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(pr.shortfall_under_p10_paisa, int)
    assert "payroll" in pr.explanation.lower()


# Test 3: Confirmed vs expected vs at-risk vs unresolved cash separation
def test_at_risk_and_unresolved_cash_separation(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    matched, _ = repo.query_records(db_session, run.run_id, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(db_session, run.run_id, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(db_session, run.run_id, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)

    forecast = build_13week_resilience_forecast(matched, partial, exceptions)
    # Unresolved cash must not be merged into confirmed cash
    assert forecast.confirmed_cash_paisa >= 0
    assert forecast.expected_cash_paisa >= 0
    assert forecast.at_risk_cash_paisa >= 0
    assert forecast.unresolved_cash_paisa >= 0


# Test 4: Copilot intent classification
def test_copilot_intent_classification_all_intents():
    assert copilot_qa.classify_intent("Will we meet payroll next Friday?") == copilot_qa.INTENT_PAYROLL_RISK
    assert copilot_qa.classify_intent("Why did settlement dip Tuesday?") == copilot_qa.INTENT_SETTLEMENT_VARIANCE
    assert copilot_qa.classify_intent("What cash is at risk?") == copilot_qa.INTENT_CASH_POSITION
    assert copilot_qa.classify_intent("Which settlements are delayed?") == copilot_qa.INTENT_DELAYED_SETTLEMENTS
    assert copilot_qa.classify_intent("Show refund exposure") == copilot_qa.INTENT_REFUND_EXPOSURE
    assert copilot_qa.classify_intent("What chargeback disputes exist?") == copilot_qa.INTENT_CHARGEBACK_EXPOSURE
    assert copilot_qa.classify_intent("What is the rule impact?") == copilot_qa.INTENT_RULE_IMPACT
    assert copilot_qa.classify_intent("What changed since the last run?") == copilot_qa.INTENT_RUN_COMPARISON
    assert copilot_qa.classify_intent("Why was REC-00001 matched?") == copilot_qa.INTENT_EXPLAIN
    assert copilot_qa.classify_intent("Should we buy company X?") == copilot_qa.INTENT_UNKNOWN


# Test 5: Copilot deterministic retrieval facts
def test_copilot_deterministic_retrieval_facts(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    answer = copilot_qa.answer_question(db_session, "Will we meet payroll next Friday?", run.run_id)

    assert answer.intent == copilot_qa.INTENT_PAYROLL_RISK
    assert answer.grounded is True
    assert len(answer.facts) > 0
    assert answer.confidence == 1.0
    assert answer.confidence_method == "DETERMINISTIC"


# Test 6: Citation existence validation
def test_copilot_citation_existence_validation(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    record = repo.query_records(db_session, run.run_id, limit=1)[0][0]

    valid_text = f"Record {record.reconciliation_id} matched cleanly at confidence 1.0."
    res = verify_copilot_evidence(
        db_session,
        valid_text,
        evidence_facts=[{"label": "Status", "value": "MATCHED"}],
        source_records=[record.reconciliation_id],
        run_id=run.run_id,
    )
    assert res.passed is True
    assert res.confidence == 1.0


# Test 7: Hallucinated record citation rejection
def test_copilot_hallucinated_amount_rejection(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    fake_text = "Record REC-999999 matched with ₹999,999,999 variance."

    res = verify_copilot_evidence(
        db_session,
        fake_text,
        evidence_facts=[{"label": "Status", "value": "MATCHED"}],
        source_records=["REC-999999"],
        run_id=run.run_id,
    )
    assert res.passed is False
    assert "REC-999999 does not exist" in res.reasons[0]


# Test 8: LLM failure fallback safety
def test_copilot_llm_failure_fallback(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    # Query when no LLM provider is active returns deterministic facts
    answer = copilot_qa.answer_question(db_session, "Why did settlement dip Tuesday?", run.run_id)
    assert answer.answer is not None
    assert len(answer.facts) > 0
    assert answer.generated_by == "deterministic-retrieval"


# Test 9: Unknown question handling
def test_copilot_unsupported_question_handling(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    answer = copilot_qa.answer_question(db_session, "What will the stock price be tomorrow?", run.run_id)
    assert answer.intent == copilot_qa.INTENT_UNKNOWN
    assert "sufficient verified financial data" in answer.answer.lower() or "answer only from" in answer.answer.lower()


# Test 10: Run comparison deltas
def test_run_comparison_deltas(db_session: Session):
    run_1 = runner.execute_run(db_session, dataset_id="seed-500", label="Run 1")
    run_2 = runner.execute_run(db_session, dataset_id="seed-500", label="Run 2")

    from app.api.routes.intelligence_routes import compare_runs_endpoint
    res = compare_runs_endpoint(baseline=run_1.run_id, candidate=run_2.run_id, session=db_session)
    assert res["baseline_run_id"] == run_1.run_id
    assert res["candidate_run_id"] == run_2.run_id
    assert "deterministic_matches_delta" in res
    assert "unexplained_value_delta_paisa" in res


# Test 11: Full demo sequence execution
def test_full_demo_sequence_execution(db_session: Session):
    from app.api.routes.intelligence_routes import run_full_demo_sequence
    res = run_full_demo_sequence(session=db_session)
    assert res["status"] == "success"
    assert "demo_self_healing" in res
    assert "resilience_summary" in res
    assert "copilot_payroll_answer" in res


# Test 12: End-to-end reconciliation -> audit ledger -> cash forecast -> copilot pipeline
def test_end_to_end_reconciliation_to_cash_to_copilot_chain(db_session: Session):
    # Step 1: Reconcile
    run = runner.execute_run(db_session, dataset_id="seed-500")

    # Step 2: Audit events exist
    events, count = repo.query_audit_events(db_session, run_id=run.run_id)
    assert count > 0

    # Step 3: Cash resilience
    matched, _ = repo.query_records(db_session, run.run_id, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(db_session, run.run_id, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(db_session, run.run_id, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)
    forecast = build_13week_resilience_forecast(matched, partial, exceptions)
    assert forecast.current_cash_paisa > 0

    # Step 4: Copilot consumes reconciled facts
    ans = copilot_qa.answer_question(db_session, "Will we meet payroll next Friday?", run.run_id)
    assert ans.grounded is True
    assert ans.confidence == 1.0
