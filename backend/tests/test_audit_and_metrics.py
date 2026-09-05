"""Audit trail creation and run metric computation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.enums import (
    AuditAction,
    ConfidenceMethod,
    MatchType,
    ReasonCode,
    ReconciliationStatus,
)
from app.domain.reconciliation import ReconciliationResult
from app.services.metrics.calculator import (
    compute_run_metrics,
    reason_code_distribution,
    status_distribution,
)
from tests.conftest import (
    make_bank_credit,
    make_dataset,
    make_invoice,
    make_order,
    make_settlement,
    simple_case,
)


# --- 14. audit event creation ---------------------------------------------
def test_run_emits_start_and_completion_events(engine):
    output = engine.run(simple_case(), run_id="RUN-00042")
    actions = [e.action for e in output.audit_events]
    assert AuditAction.RUN_STARTED in actions
    assert AuditAction.RUN_COMPLETED in actions
    assert AuditAction.DATA_INGESTED in actions
    assert all(e.run_id == "RUN-00042" for e in output.audit_events)
    assert all(e.audit_id for e in output.audit_events)
    assert all(e.system_version for e in output.audit_events)


def test_every_match_writes_an_auditable_calculation(engine):
    output = engine.run(simple_case(), run_id="RUN-00001")
    match_events = [
        e for e in output.audit_events if e.action is AuditAction.RECONCILIATION_MATCH
    ]
    assert len(match_events) == 1
    event = match_events[0]
    assert event.reconciliation_id
    assert event.previous_state == "UNRECONCILED"
    assert event.new_state == "MATCHED"
    assert event.calculation, "an audit event must carry the literal arithmetic"
    assert event.source_records
    assert event.evidence
    assert event.detail["confidence"] == 1.0
    assert event.detail["variance_paisa"] == 0


def test_invariant_verification_is_audited_separately(engine):
    output = engine.run(simple_case(), run_id="RUN-00001")
    verified = [
        e for e in output.audit_events if e.action is AuditAction.INVARIANT_VERIFIED
    ]
    assert len(verified) == 1
    assert "expected" in verified[0].calculation
    assert verified[0].rule_id == "RULE-NET-001"


def test_invariant_violation_is_audited_as_a_violation(engine):
    order = make_order(gross=1_000_000)
    broken = make_settlement(gross=1_000_000, tds_override=99_999)
    credit = make_bank_credit(amount=broken.net_amount_paisa)
    output = engine.run(
        make_dataset([order], [broken], [credit], [make_invoice()]), run_id="R"
    )
    actions = [e.action for e in output.audit_events]
    assert AuditAction.INVARIANT_VIOLATED in actions
    assert AuditAction.INVARIANT_VERIFIED not in actions


def test_adjustments_are_audited_with_their_evidence(engine):
    refund = 250_000
    order = make_order(gross=1_000_000, refund=refund)
    settlement = make_settlement(
        gross=1_000_000, refund_adjustment=refund,
        netted_refund_payment_ids=["PAY-89001"],
    )
    credit = make_bank_credit(amount=settlement.net_amount_paisa)
    output = engine.run(make_dataset([order], [settlement], [credit], [make_invoice()]))
    events = [
        e for e in output.audit_events if e.action is AuditAction.ADJUSTMENT_RECORDED
    ]
    assert len(events) == 1
    assert events[0].evidence
    assert events[0].detail["adjustment"]["amount_paisa"] == refund


def test_audit_ids_are_unique_and_sequential(engine):
    output = engine.run(simple_case())
    ids = [e.audit_id for e in output.audit_events]
    assert len(ids) == len(set(ids))
    assert ids == sorted(ids)


# --- 15/16. match rate and throughput -------------------------------------
def _fake_result(status: ReconciliationStatus, actual: int = 0, variance: int = 0):
    return ReconciliationResult(
        reconciliation_id=f"REC-{status.value}",
        status=status,
        match_type=MatchType.EXACT_PAYMENT_ID,
        confidence=1.0,
        confidence_method=ConfidenceMethod.ACCOUNTING_INVARIANT,
        actual_amount_paisa=actual,
        variance_paisa=variance,
    )


def test_match_rate_is_matched_over_processed():
    results = (
        [_fake_result(ReconciliationStatus.MATCHED, 1000) for _ in range(472)]
        + [_fake_result(ReconciliationStatus.PARTIAL_MATCH) for _ in range(11)]
        + [_fake_result(ReconciliationStatus.REVIEW_REQUIRED) for _ in range(9)]
        + [_fake_result(ReconciliationStatus.EXCEPTION) for _ in range(8)]
    )
    started = datetime.now(timezone.utc)
    metrics = compute_run_metrics(
        run_id="RUN-00001",
        results=results,
        dataset=make_dataset(),
        started_at=started,
        completed_at=started + timedelta(milliseconds=1240),
        processing_time_ms=1240.0,
        engine_version="test",
    )
    assert metrics.records_processed == 500
    assert metrics.deterministic_matches == 472
    assert metrics.match_rate == 472 / 500
    assert metrics.residuals == 9 + 8
    assert metrics.exception_rate == 8 / 500


def test_throughput_is_records_over_seconds():
    results = [_fake_result(ReconciliationStatus.MATCHED) for _ in range(500)]
    started = datetime.now(timezone.utc)
    metrics = compute_run_metrics(
        run_id="RUN-00001",
        results=results,
        dataset=make_dataset(),
        started_at=started,
        completed_at=started + timedelta(milliseconds=1240),
        processing_time_ms=1240.0,
        engine_version="test",
    )
    # 500 records in 1.24 s = 403.2 records/sec
    assert round(metrics.throughput_rps, 1) == 403.2


def test_metrics_do_not_divide_by_zero_on_an_empty_run():
    started = datetime.now(timezone.utc)
    metrics = compute_run_metrics(
        run_id="RUN-00000",
        results=[],
        dataset=make_dataset(),
        started_at=started,
        completed_at=started,
        processing_time_ms=0.0,
        engine_version="test",
    )
    assert metrics.match_rate == 0.0
    assert metrics.throughput_rps == 0.0


def test_status_distribution_reports_every_status_including_zeros():
    counts = status_distribution([_fake_result(ReconciliationStatus.MATCHED)])
    assert counts["MATCHED"] == 1
    assert counts["EXCEPTION"] == 0
    assert set(counts) == {s.value for s in ReconciliationStatus}


def test_metrics_are_measured_from_the_actual_run(engine):
    output = engine.run(simple_case(), run_id="RUN-00007")
    metrics = output.metrics
    assert metrics.run_id == "RUN-00007"
    assert metrics.records_processed == len(output.results) == 1
    assert metrics.match_rate == 1.0
    assert metrics.processing_time_ms > 0
    assert metrics.throughput_rps > 0
    assert metrics.total_reconciled_paisa == output.results[0].actual_amount_paisa
    assert metrics.unexplained_value_paisa == 0


def test_matched_records_contribute_zero_unexplained_value(engine):
    output = engine.run(simple_case())
    assert all(
        r.unexplained_value_paisa == 0
        for r in output.results
        if r.status is ReconciliationStatus.MATCHED
    )


def test_reason_code_distribution_counts_codes():
    order = ReconciliationStatus.REVIEW_REQUIRED
    result = _fake_result(order)


    result.reason_codes = [ReasonCode.TDS_MISMATCH, ReasonCode.NET_AMOUNT_VARIANCE]
    counts = reason_code_distribution([result])
    assert counts["TDS_MISMATCH"] == 1
    assert counts["NET_AMOUNT_VARIANCE"] == 1
