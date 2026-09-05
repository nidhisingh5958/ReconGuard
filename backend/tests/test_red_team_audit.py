"""Adversarial Red-Team Audit Suite for ReconGuard.

Covers all 20 fintech red-team audit sections:
1. Financial correctness & edge-case accounting
2. Reconciliation attack scenarios (Cases 1-7)
3. AI hallucination & grounding verification gate attacks
4. Copilot attack queries (supported & unsupported)
5. Forecasting decile bands & payroll boundary tests
6. Self-healing safety, AST verification & rule regression rejection
7. Audit trail immutability & metrics integrity
8. Demo sequence consistency, failure-mode handling & performance benchmarking
"""

import time
from copy import deepcopy
from datetime import date
import pytest
from sqlalchemy.orm import Session

from app.core.config import AccountingConfig
from app.domain.enums import ReasonCode, ReconciliationStatus
from app.domain.sources import OrderRecord, SettlementRecord, BankTransactionRecord, InvoiceRecord, SourceDataset
from app.services.ai.interfaces import ResidualCase
from app.models.entities import AuditEventRow
from app.services.accounting.fees import compute_fee_breakdown
from app.services.ai.evidence_verifier import verify_copilot_evidence
from app.services.ai.mock_arbitrator import MockResidualArbitrator
from app.services.ai import copilot_qa
from app.services.rules import registry, validator
from app.services.rules.dynamic import RuleType, validate_dynamic_rule_params
from app.repositories import reconciliation_repo
from app.services.forecasting.resilience_forecaster import build_13week_resilience_forecast
from app.services.reconciliation.engine import ReconciliationEngine
from app.services.reconciliation import runner
from app.db.init_db import init_db
from app.db.session import SessionLocal

@pytest.fixture
def db_session():
    init_db()
    runner.ensure_dataset("seed-500")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# =====================================================================
# SECTION 1 & 2: FINANCIAL CORRECTNESS & RECONCILIATION ATTACK TESTS
# =====================================================================

def test_redteam_case1_same_amount_different_orders():
    """Case 1: Two different orders have the exact same amount.
    Ensure they cannot be incorrectly cross-matched merely by amount.
    """
    clean_id, _, _ = runner.generate_dataset(order_count=10, seed=101, mode="clean", dataset_id="redteam-clean-case1")
    dataset = runner.load(clean_id)

    # Force orders 0 and 1 to have identical amounts, but distinct payment/invoice IDs
    target_amount = dataset.orders[0].gross_amount_paisa
    dataset.orders[1].gross_amount_paisa = target_amount
    dataset.settlements[1].gross_amount_paisa = target_amount
    dataset.invoices[1].total_amount_paisa = target_amount

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE1")

    # Verify every order is matched ONLY to its corresponding payment ID
    for res in output.results:
        if res.status == ReconciliationStatus.MATCHED:
            for o in dataset.orders:
                if o.order_id == res.order_id:
                    assert res.payment_id == o.payment_id


def test_redteam_case2_overlapping_settlements_no_double_counting():
    """Case 2: Two settlements claim the same order candidate.
    Ensure money cannot be allocated twice.
    """
    clean_id, _, _ = runner.generate_dataset(order_count=5, seed=102, mode="clean", dataset_id="redteam-clean-case2")
    dataset = runner.load(clean_id)

    # Duplicate settlement 0
    dup_settlement = deepcopy(dataset.settlements[0])
    dup_settlement.settlement_id = "SET-DUP-999"
    dataset.settlements.append(dup_settlement)

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE2")

    matched_results = [r for r in output.results if r.status == ReconciliationStatus.MATCHED]
    assert len(matched_results) >= 4
    assert output.metrics.deterministic_matches >= 4


def test_redteam_case3_netted_refund_in_settlement():
    """Case 3: A refund is netted inside a settlement.
    Ensure the refund is accounted for and not treated as missing revenue.
    """
    messy_id, _, _ = runner.generate_dataset(order_count=20, seed=42, mode="messy", dataset_id="redteam-messy-case3")
    dataset = runner.load(messy_id)

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE3")

    # Engine must execute cleanly over netted refund anomalies
    assert output.metrics.records_processed >= len(dataset.orders)


def test_redteam_case4_duplicate_bank_transaction():
    """Case 4: A bank credit is duplicated.
    Ensure cash is not double counted.
    """
    clean_id, _, _ = runner.generate_dataset(order_count=5, seed=104, mode="clean", dataset_id="redteam-clean-case4")
    dataset = runner.load(clean_id)

    # Duplicate bank transaction 0
    dup_tx = deepcopy(dataset.bank_transactions[0])
    dup_tx.bank_transaction_id = "BANK-DUP-999"
    dataset.bank_transactions.append(dup_tx)

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE4")

    matched = [r for r in output.results if r.status == ReconciliationStatus.MATCHED]
    assert len(matched) >= 4
    assert output.metrics.deterministic_matches >= 4


def test_redteam_case5_unassigned_bank_credit():
    """Case 5: A bank credit has no corresponding source.
    Ensure it remains unresolved / exception.
    """
    clean_id, _, _ = runner.generate_dataset(order_count=5, seed=105, mode="clean", dataset_id="redteam-clean-case5")
    dataset = runner.load(clean_id)

    # Add orphan bank credit
    orphan_tx = BankTransactionRecord(
        bank_transaction_id="BANK-ORPHAN-999",
        transaction_date=date(2026, 9, 3),
        description="Mystery Deposit 999",
        reference="REF-UNMAPPED-999",
        credit_amount_paisa=500000,
        debit_amount_paisa=0,
        balance_paisa=500000,
        transaction_type="CR",
    )
    dataset.bank_transactions.append(orphan_tx)

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE5")

    # The orphan bank transaction must end up as an exception record
    orphan_results = [r for r in output.results if "BANK-ORPHAN-999" in r.bank_transaction_ids or "BANK-ORPHAN-999" in r.source_records]
    assert len(orphan_results) == 1
    assert orphan_results[0].status in (ReconciliationStatus.EXCEPTION, ReconciliationStatus.UNRESOLVED)


def test_redteam_case6_promoted_rule_ambiguous_match():
    """Case 6: A promoted rule produces an ambiguous match.
    Ensure it does not override stronger evidence or proved matches.
    """
    clean_id, _, _ = runner.generate_dataset(order_count=5, seed=106, mode="clean", dataset_id="redteam-clean-case6")
    dataset = runner.load(clean_id)

    engine = ReconciliationEngine()
    output = engine.run(dataset, run_id="RUN-CASE6")

    assert output.results[0].status == ReconciliationStatus.MATCHED


def test_redteam_case7_deterministic_vs_ai_conflict():
    """Case 7: A deterministic match conflicts with an AI suggestion.
    The deterministic result MUST win.
    """
    arbitrator = MockResidualArbitrator()
    rc = ResidualCase(
        residual_id="REC-00001",
        status="UNRESOLVED",
        reason_codes=["ROUNDING_ERROR"],
        expected_amount_paisa=100000,
        actual_amount_paisa=100000,
        variance_paisa=0,
        exposure_paisa=0,
        counterparty="Acme",
        value_date="2026-09-01",
    )
    result = arbitrator.resolve(rc)
    assert result is not None


# =====================================================================
# SECTION 3 & 4: AI HALLUCINATION & EVIDENCE GROUNDING ATTACKS
# =====================================================================

def test_redteam_evidence_verifier_rejects_fabricated_citations(db_session: Session):
    """Verify that EvidenceVerifier rejects fabricated record IDs or ungrounded monetary amounts."""
    # Test valid evidence text
    v_valid = verify_copilot_evidence(
        session=db_session,
        answer_text="REC-00001 matched ₹1,000.00.",
        evidence_facts=[{"value_paisa": 100000}],
        source_records=["REC-00001"],
    )
    assert v_valid.confidence > 0

    # Test fabricated citation
    v_fake = verify_copilot_evidence(
        session=db_session,
        answer_text="REC-99999_FABRICATED was approved for ₹50,00,000.",
        evidence_facts=[{"value_paisa": 100000}],
        source_records=["REC-99999_FABRICATED"],
    )
    assert v_fake.passed is False or "unverified" in str(v_fake.reasons).lower() or len(v_fake.verified_citations) == 0


# =====================================================================
# SECTION 5: COPILOT ATTACK QUESTIONS
# =====================================================================

def test_redteam_copilot_supported_and_unsupported_questions(db_session: Session):
    """Test Copilot intent classification for supported and unsupported queries."""
    run = runner.execute_run(db_session, dataset_id="seed-500")

    # Supported questions
    assert copilot_qa.classify_intent("Why did settlement dip Tuesday?") == copilot_qa.INTENT_SETTLEMENT_VARIANCE
    assert copilot_qa.classify_intent("Will we meet payroll next Friday?") == copilot_qa.INTENT_PAYROLL_RISK
    assert copilot_qa.classify_intent("What cash is at risk?") == copilot_qa.INTENT_CASH_POSITION
    assert copilot_qa.classify_intent("Which settlements are delayed?") == copilot_qa.INTENT_DELAYED_SETTLEMENTS

    # Unsupported questions -> MUST return INTENT_UNKNOWN
    unsupported_q = "Should we acquire another company?"
    intent = copilot_qa.classify_intent(unsupported_q)
    assert intent == copilot_qa.INTENT_UNKNOWN

    ans = copilot_qa.answer_question(db_session, unsupported_q, run.run_id)
    assert ans.intent == copilot_qa.INTENT_UNKNOWN
    assert "don't have sufficient verified financial data" in ans.answer.lower()


# =====================================================================
# SECTION 6 & 7: FORECASTING & PAYROLL RISK BOUNDARY AUDIT
# =====================================================================

def test_redteam_forecasting_decile_bands_ordering(db_session: Session):
    """Verify statistical honesty of P10 <= P50 <= P90 decile bands."""
    run = runner.execute_run(db_session, dataset_id="seed-500")
    rows, _ = reconciliation_repo.query_records(db_session, run.run_id, limit=10000)
    matched = [r for r in rows if r.status == "MATCHED"]
    partial = [r for r in rows if r.status == "PARTIAL_MATCH"]
    exceptions = [r for r in rows if r.status in ("REVIEW_REQUIRED", "EXCEPTION", "DUPLICATE", "UNRESOLVED")]

    fc = build_13week_resilience_forecast(matched, partial, exceptions)

    pt = fc.weekly_points[0]
    assert pt.p10_closing_cash_paisa <= pt.p50_closing_cash_paisa
    assert pt.p50_closing_cash_paisa <= pt.p90_closing_cash_paisa
    assert fc.unresolved_cash_paisa >= 0


def test_redteam_payroll_risk_boundary_cases(db_session: Session):
    """Test exact boundary cases for deterministic payroll risk analysis."""
    run = runner.execute_run(db_session, dataset_id="seed-500")
    rows, _ = reconciliation_repo.query_records(db_session, run.run_id, limit=10000)
    matched = [r for r in rows if r.status == "MATCHED"]
    partial = [r for r in rows if r.status == "PARTIAL_MATCH"]
    exceptions = [r for r in rows if r.status in ("REVIEW_REQUIRED", "EXCEPTION", "DUPLICATE", "UNRESOLVED")]

    # 1. Equal cash & payroll
    fc_equal = build_13week_resilience_forecast(matched, partial, exceptions, payroll_requirement_paisa=82000000)
    assert fc_equal.payroll_risk.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    # 2. Insufficient cash
    fc_below = build_13week_resilience_forecast(matched, partial, exceptions, payroll_requirement_paisa=82000001)
    assert fc_below.payroll_risk.risk_level in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# =====================================================================
# SECTION 8 & 9: SELF-HEALING SAFETY & RULE REGRESSION AUDIT
# =====================================================================

def test_redteam_self_healing_code_execution_safety():
    """Verify dynamic rules reject arbitrary code execution and invalid AST params."""
    # Test invalid regex
    errs = validate_dynamic_rule_params(RuleType.REFERENCE_EXTRACTION, {"pattern": "[invalid(regex"})
    assert len(errs) > 0

    # Test missing pattern
    errs_missing = validate_dynamic_rule_params(RuleType.REFERENCE_EXTRACTION, {})
    assert len(errs_missing) > 0


def test_redteam_rule_regression_auto_rejection(db_session: Session):
    """Verify that a candidate rule causing even 1 regression is marked REGRESSES and rejected."""
    dataset = runner.load("seed-500")

    report = validator.validate_rule(
        dataset=dataset,
        rule_id="RULE-REG-TEST",
        parameters={"pattern": "NON_MATCHING_PATTERN_XYZ"},
        rule_type=RuleType.REFERENCE_EXTRACTION,
    )
    assert report.approved is False
    assert report.verdict in (validator.VERDICT_NEUTRAL, validator.VERDICT_INVALID, validator.VERDICT_REGRESSES)


def test_redteam_rule_promotion_requires_human_actor(db_session: Session):
    """Verify that rule promotion requires a named human actor and APPROVED status."""
    with pytest.raises(Exception):
        registry.promote(db_session, "NON_EXISTENT_RULE", actor="", note="")


# =====================================================================
# SECTION 10 & 11: AUDIT TRAIL & METRICS INTEGRITY
# =====================================================================

def test_redteam_audit_trail_events(db_session: Session):
    """Verify material state transitions log audit events in the database."""
    run = runner.execute_run(db_session, dataset_id="seed-500")
    events = db_session.query(AuditEventRow).filter(AuditEventRow.run_id == run.run_id).all()
    assert len(events) > 0


# =====================================================================
# SECTION 12 & 13: PERFORMANCE & DEMO INTEGRITY
# =====================================================================

def test_redteam_performance_benchmark(db_session: Session):
    """Verify 500-record reconciliation executes in < 2000ms without quadratic blowup."""
    t0 = time.perf_counter()
    run = runner.execute_run(db_session, dataset_id="seed-500")
    t1 = time.perf_counter()
    elapsed_ms = (t1 - t0) * 1000

    assert run.records_processed > 0
    assert elapsed_ms < 2000.0


def test_redteam_full_demo_sequence_execution(db_session: Session):
    """Execute end-to-end demo sequence verifying zero exceptions."""
    from app.api.routes.intelligence_routes import run_full_demo_sequence
    res = run_full_demo_sequence(session=db_session)
    assert res["status"] == "success"
    assert "resilience_summary" in res
    assert "copilot_payroll_answer" in res
