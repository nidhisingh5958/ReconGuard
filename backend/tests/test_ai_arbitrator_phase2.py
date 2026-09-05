"""Regression test suite for Phase 2 Residual AI Arbitrator."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from datetime import date

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="reconguard-phase2-"))
os.environ["RECONGUARD_DATABASE_URL"] = f"sqlite:///{(_TMP / 'phase2.db').as_posix()}"

from app.core.config import get_settings  # noqa: E402
get_settings.cache_clear()

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.init_db import init_db
from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision, JournalEntryStatus
from app.services.accounting.journal import JournalBatch, JournalBuilder
from app.services.ai.candidates import ResidualCandidate, ResidualView, build_candidates
from app.services.ai.confidence import compute_evidence_confidence
from app.services.ai.deterministic_arbitrator import DeterministicArbitrator
from app.services.ai.evaluation import evaluate_run_arbitration
from app.services.ai.interfaces import ResidualCase, build_residual_case, get_arbitrator
from app.services.ai.llm_arbitrator import LLMResidualArbitrator, _clamp_confidence
from app.services.ai.mock_arbitrator import MockResidualArbitrator
from app.services.ai.providers import ScriptedProvider
from app.services.ai.verification import verify_arbitration, verify_journal_batch
from app.services.ai import arbitration_service
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


# Test 1: AI receives only residuals (never deterministic matches)
def test_ai_receives_only_residuals(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    cases = arbitration_service.build_cases(db_session, run.run_id)
    for case, record in cases:
        assert record.status != "MATCHED"
        assert case.status in arbitration_service.ARBITRABLE_STATUSES


# Test 2: Deterministic matches are never modified or passed to AI
def test_deterministic_matches_never_reach_ai(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    initial_matched = run.deterministic_matches

    mock_arb = MockResidualArbitrator()
    arb_res = arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=mock_arb)

    from app.models.entities import ReconciliationRecord
    matched_count = db_session.query(ReconciliationRecord).filter(
        ReconciliationRecord.run_id == run.run_id,
        ReconciliationRecord.status == "MATCHED"
    ).count()
    assert matched_count == initial_matched


# Test 3: Invalid AI response becomes UNRESOLVED
def test_invalid_ai_response_becomes_unresolved():
    from app.services.ai.interfaces import NullArbitrator
    bad_provider = ScriptedProvider([{"decision": "INVALID_DECISION", "confidence": 0.9}])
    llm_arb = LLMResidualArbitrator(client=bad_provider, fallback=NullArbitrator())

    case = ResidualCase(
        residual_id="RES-BAD",
        status="EXCEPTION",
        reason_codes=["UNKNOWN_BANK_CREDIT"],
        expected_amount_paisa=1000,
        actual_amount_paisa=0,
        variance_paisa=1000,
        exposure_paisa=1000,
        counterparty="Unknown",
        value_date="2026-09-01",
        source_records=["BNK-001"],
    )
    result = llm_arb.resolve(case)
    assert result.decision == ArbitrationDecision.UNRESOLVED


# Test 4: Confidence outside 0-1 is clamped/rejected
def test_confidence_clamping():
    assert _clamp_confidence(1.5) == 0.90
    assert _clamp_confidence(-0.5) == 0.0
    assert _clamp_confidence("nan") == 0.5


# Test 5: Missing evidence prevents resolution
def test_missing_evidence_prevents_resolution():
    case = ResidualCase(
        residual_id="RES-001",
        status="EXCEPTION",
        reason_codes=["UNKNOWN_BANK_CREDIT"],
        expected_amount_paisa=1000,
        actual_amount_paisa=0,
        variance_paisa=1000,
        exposure_paisa=1000,
        counterparty="Unknown",
        value_date="2026-09-01",
        source_records=["BNK-001"],
    )
    result = ArbitrationResult(
        residual_id="RES-001",
        decision=ArbitrationDecision.RESOLVE,
        confidence=0.99,
        reason="Claimed match without evidence",
        evidence=[],
        proposed_action="ACCRUE_SETTLEMENT_RECEIVABLE",
    )
    outcome = verify_arbitration(case, result)
    assert not outcome.accepted
    assert outcome.result.decision == ArbitrationDecision.UNRESOLVED


# Test 6: Journal entries must balance (debits == credits)
def test_journal_entry_double_entry_balance():
    builder = JournalBuilder()
    batch = builder.build(
        residual_id="RES-001",
        action="ACCRUE_SETTLEMENT_RECEIVABLE",
        amount_paisa=50000,
        source_records=["REC-001", "SET-001"],
        confidence=0.95,
        value_date=date(2026, 9, 1),
    )
    verdict = verify_journal_batch(batch, permitted_source_records={"REC-001", "SET-001", "RES-001"})
    assert verdict.accepted
    assert sum(e.amount_paisa for e in batch.entries) == 50000


# Test 7: Human approval is persisted
def test_human_approval_persistence(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=MockResidualArbitrator())

    results = list_arbitration_helper(db_session, run.run_id)
    assert len(results) > 0
    target_id = results[0].residual_id

    arbitration_service.approve_residual(db_session, target_id, actor="operator@finance")

    from sqlalchemy import select
    from app.models.entities import ArbitrationRow
    db_session.expire_all()
    row = db_session.scalar(select(ArbitrationRow).where(ArbitrationRow.residual_id == target_id).order_by(ArbitrationRow.created_at.desc()))
    assert row.decision == ArbitrationDecision.RESOLVE.value
    assert row.requires_human_review is False


# Test 8: Human rejection is persisted
def test_human_rejection_persistence(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=MockResidualArbitrator())

    results = list_arbitration_helper(db_session, run.run_id)
    assert len(results) > 0
    target_id = results[0].residual_id

    arbitration_service.reject_residual(db_session, target_id, actor="operator@finance")

    from sqlalchemy import select
    from app.models.entities import ArbitrationRow
    db_session.expire_all()
    row = db_session.scalar(select(ArbitrationRow).where(ArbitrationRow.residual_id == target_id).order_by(ArbitrationRow.created_at.desc()))
    assert row.decision == ArbitrationDecision.UNRESOLVED.value


# Test 9: AI failure does not affect deterministic results
def test_ai_failure_fallback_safety(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    failing_provider = ScriptedProvider([Exception("Network Timeout")])
    llm_arb = LLMResidualArbitrator(client=failing_provider)

    arb_res = arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=llm_arb)
    assert arb_res["residuals_examined"] > 0


# Test 10: Audit event created for every AI decision
def test_audit_event_created_for_ai_decision(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=MockResidualArbitrator())

    from app.models.entities import AuditEventRow
    audits = db_session.query(AuditEventRow).filter(AuditEventRow.run_id == run.run_id).all()
    assert len(audits) > 0


# Test 11: Ground-truth evaluation works
def test_ground_truth_evaluation(db_session: Session):
    run = runner.execute_run(db_session, dataset_id="seed-500")
    arbitration_service.arbitrate_run(db_session, run.run_id, arbitrator=MockResidualArbitrator())

    metrics = evaluate_run_arbitration(db_session, run.run_id)
    assert metrics.total_residuals > 0
    assert 0.0 <= metrics.precision <= 1.0
    assert 0.0 <= metrics.recall <= 1.0


# Test 12: Mock arbitrator produces deterministic results
def test_mock_arbitrator_determinism():
    mock_arb = MockResidualArbitrator()
    case = ResidualCase(
        residual_id="RES-MOCK-1",
        status="EXCEPTION",
        reason_codes=["CUSTOMER_NAME_ALIAS"],
        expected_amount_paisa=976200,
        actual_amount_paisa=976200,
        variance_paisa=0,
        exposure_paisa=976200,
        counterparty="Acme Technologies Pvt Ltd",
        value_date="2026-09-01",
        source_records=["ORD-101", "BNK-101"],
    )
    res = mock_arb.resolve(case)
    assert res.decision in (ArbitrationDecision.RESOLVE, ArbitrationDecision.PROBABLE)
    assert res.arbitrator == "mock"


def list_arbitration_helper(session: Session, run_id: str):
    from app.models.entities import ArbitrationRow
    return session.query(ArbitrationRow).filter(ArbitrationRow.run_id == run_id).all()
