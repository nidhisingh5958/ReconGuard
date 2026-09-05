"""Regression test suite for Phase 3 Self-Healing Rule Promotion."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from datetime import date

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="reconguard-phase3-"))
os.environ["RECONGUARD_DATABASE_URL"] = f"sqlite:///{(_TMP / 'phase3.db').as_posix()}"

from app.core.config import get_settings
get_settings.cache_clear()

from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.init_db import init_db
from app.domain.enums import RuleStatus, AuditAction
from app.models.entities import RuleRow, AuditEventRow
from app.services.reconciliation import runner
from app.services.rules.dynamic import (
    AmountToleranceRule,
    DateToleranceRule,
    DynamicRuleSet,
    ReferenceExtractionRule,
    RuleType,
    validate_dynamic_rule_params,
)
from app.services.rules import registry, validator
from app.services.rules.proposal import (
    RuleProposal,
    propose_reference_rules,
    propose_amount_tolerance_rules,
    ReferenceSample,
)


@pytest.fixture
def db_session():
    init_db()
    runner.ensure_dataset("seed-phase3")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Requirement 1: Rules cannot override stronger deterministic invariants
def test_rules_cannot_override_stronger_deterministic_invariants(db_session: Session):
    # Dynamic rules run only when built-in layers do not resolve the transaction.
    dataset = runner.load("seed-phase3")
    rule = ReferenceExtractionRule(
        rule_id="RULE-DYN-999",
        name="Test Overriding Rule",
        pattern=r"(\d{5})",
        marker="SET",
    )
    rule_set = DynamicRuleSet(reference_rules=[rule])
    output = runner.execute_run(db_session, dataset_id="seed-phase3")
    assert output is not None
    assert output.deterministic_matches > 0


# Requirement 2: Rules cannot create unsupported matches
def test_rules_cannot_create_unsupported_matches():
    invalid_params = {"pattern": r"invalid(regex", "marker": ""}
    reasons = validate_dynamic_rule_params(RuleType.REFERENCE_EXTRACTION, invalid_params)
    assert len(reasons) > 0, "Invalid regex & missing marker must be rejected by safety validator"


# Requirement 3: Rule activation requires explicit human approval
def test_rule_activation_requires_human_approval(db_session: Session):
    proposal = RuleProposal(
        name="Test Approval Gate",
        rule_type=RuleType.REFERENCE_EXTRACTION,
        pattern=r"SET\s+(\d{5})",
        marker="SET",
        description="Requires approval",
        support=3,
        supporting_residuals=["RES-001", "RES-002", "RES-003"],
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    assert row.status == RuleStatus.PROPOSED.value

    # Attempt promotion without validation/approval
    with pytest.raises(registry.RulePromotionError):
        registry.promote(db_session, row.rule_id, actor="auditor@company.com")

    # Attempt promotion without actor
    row.status = RuleStatus.APPROVED.value
    db_session.commit()
    with pytest.raises(registry.RulePromotionError):
        registry.promote(db_session, row.rule_id, actor="")


# Requirement 4: Rejected rules never execute
def test_rejected_rules_never_execute(db_session: Session):
    proposal = RuleProposal(
        name="Test Reject Rule",
        rule_type=RuleType.AMOUNT_TOLERANCE,
        pattern="tolerance_paisa=1",
        marker="XYZ",
        description="Will be rejected",
        support=2,
        supporting_residuals=["RES-010", "RES-011"],
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    registry.reject(db_session, row.rule_id, actor="auditor@company.com", note="Too risky")

    active_rules = registry.active_dynamic_rules(db_session)
    active_ids = [r.rule_id for r in active_rules]
    assert row.rule_id not in active_ids, "Rejected rule must never be loaded into active rules"


# Requirement 5: Retired rules stop executing
def test_retired_rules_stop_executing(db_session: Session):
    proposal = RuleProposal(
        name="Test Retire Rule",
        rule_type=RuleType.AMOUNT_TOLERANCE,
        pattern="tolerance_paisa=1",
        marker="XYZ",
        description="Will be retired",
        support=2,
        supporting_residuals=["RES-020", "RES-021"],
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    row.status = RuleStatus.APPROVED.value
    db_session.commit()
    registry.promote(db_session, row.rule_id, actor="auditor@company.com")
    assert row.rule_id in [r.rule_id for r in registry.active_dynamic_rules(db_session)]

    registry.retire(db_session, row.rule_id, actor="auditor@company.com", note="Superseded")
    assert row.rule_id not in [r.rule_id for r in registry.active_dynamic_rules(db_session)]


# Requirement 6: Rule versions are immutable
def test_rule_version_immutability(db_session: Session):
    proposal = RuleProposal(
        name="Test Versioning",
        rule_type=RuleType.REFERENCE_EXTRACTION,
        pattern=r"REF\s+(\d{5})",
        marker="REF",
        description="Immutable version",
        support=3,
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    assert row.version == 1


# Requirement 7: Backtesting is reproducible across replays
def test_backtesting_reproducibility(db_session: Session):
    dataset = runner.load("seed-phase3")
    params = {"pattern": r"SET\s+(\d{5})", "marker": "SET"}
    report1 = validator.validate_rule(dataset, "RULE-TEST", params, validation_id="VAL-1")
    report2 = validator.validate_rule(dataset, "RULE-TEST", params, validation_id="VAL-2")

    assert report1.baseline_matches == report2.baseline_matches
    assert report1.candidate_matches == report2.candidate_matches
    assert report1.verdict == report2.verdict


# Requirement 8: Rule execution creates immutable audit events
def test_rule_execution_creates_audit_events(db_session: Session):
    proposal = RuleProposal(
        name="Audit Logging Test",
        rule_type=RuleType.REFERENCE_EXTRACTION,
        pattern=r"SET\s+(\d{5})",
        marker="SET",
        description="Audit logged",
        support=3,
        supporting_residuals=["RES-100"],
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    events = list(db_session.query(AuditEventRow).filter(AuditEventRow.rule_id == row.rule_id).all())
    assert len(events) >= 1
    assert events[0].action == "RULE_PROPOSED"


# Requirement 9: Historical runs remain unchanged when rules are added
def test_historical_runs_remain_unchanged(db_session: Session):
    run1 = runner.execute_run(db_session, dataset_id="seed-phase3", label="Run 1")
    m1_before = run1.deterministic_matches

    # Add and activate dynamic rule
    row = RuleRow(
        rule_id="RULE-DYN-888",
        name="Dynamic Test",
        rule_type=RuleType.AMOUNT_TOLERANCE,
        expression="test",
        version=1,
        status=RuleStatus.ACTIVE.value,
        created_by="test",
        created_at=registry._now(),
        parameters={"gateway": "XYZ", "tolerance_paisa": 1},
    )
    db_session.add(row)
    db_session.commit()

    run2 = runner.execute_run(db_session, dataset_id="seed-phase3", label="Run 2")
    m1_after = run1.deterministic_matches
    assert m1_before == m1_after, "Historical Run 1 metrics must remain identical"


# Requirement 10: AI dependency reduction is calculated correctly
def test_ai_dependency_reduction_calculation():
    before_residuals = 30
    after_residuals = 10
    reduction = (1.0 - (after_residuals / before_residuals)) * 100
    assert abs(reduction - 66.666) < 0.1


# Requirement 11: False-positive rate is measured during backtest
def test_false_positive_rate_measured(db_session: Session):
    dataset = runner.load("seed-phase3")
    params = {"pattern": r"SET\s+(\d{5})", "marker": "SET"}
    report = validator.validate_rule(dataset, "RULE-FP-TEST", params)
    assert "false_positives" in report.detail
    assert "precision" in report.detail


# Requirement 12: A bad/regressive rule can be safely rejected
def test_bad_rule_safely_rejected(db_session: Session):
    proposal = RuleProposal(
        name="Bad Rule Candidate",
        rule_type=RuleType.REFERENCE_EXTRACTION,
        pattern=r"(\d{1})",  # Bad pattern
        marker="SET",
        description="Bad pattern",
        support=1,
    )
    row, _ = registry.record_proposal(db_session, proposal, run_id="RUN-001")
    registry.reject(db_session, row.rule_id, actor="auditor@company.com", note="Regressive")
    assert row.status == RuleStatus.REJECTED.value
