"""Arbitration, rule promotion, journals, forecasting and copilot endpoints.

Everything here sits on top of the deterministic engine and none of it is
required for reconciliation to work. Each endpoint degrades honestly when its
optional dependency is absent: arbitration falls back to deterministic policy,
forecasting reports that history is too short, and the copilot answers only what
it can retrieve.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_run_id
from app.core.config import get_settings
from app.db.session import get_session
from app.models.entities import ArbitrationRow, ReconciliationRecord, RuleRow
from app.repositories import reconciliation_repo as repo
from app.schemas.api import (
    ArbitrateRequest,
    ArbitrationListResponse,
    ArbitrationRunResponse,
    CashResilienceResponse,
    CopilotRequest,
    CopilotResponse,
    ForecastResponse,
    JournalDecisionRequest,
    JournalListResponse,
    RuleCatalogueResponse,
    RuleDecisionRequest,
    RuleValidateRequest,
    TrialBalanceResponse,
)
from app.services.accounting import chart_of_accounts as coa
from app.services.accounting import posting
from app.services.ai import arbitration_service
from app.services.ai.copilot_qa import answer_question
from app.services.ai.interfaces import get_arbitrator
from app.services.forecasting.forecaster import (
    DailyObservation,
    SettlementCycleForecaster,
)
from app.services.reconciliation import runner
from app.services.rules import registry
from app.services.rules.validator import validate_rule

router = APIRouter()

LIFECYCLE = [
    {"status": "PROPOSED", "note": "Induced from arbitration evidence in a real run."},
    {"status": "VALIDATING", "note": "Replayed against a dataset; measurement is automatic."},
    {"status": "APPROVED", "note": "The replay improved matching with zero regressions."},
    {"status": "ACTIVE", "note": "Promoted by a named human. Changes what the engine matches."},
    {"status": "REJECTED", "note": "The replay regressed or was neutral, or a human declined."},
    {"status": "RETIRED", "note": "Withdrawn or superseded by a later version."},
]


# --- arbitration ----------------------------------------------------------
@router.post(
    "/arbitration/run", response_model=ArbitrationRunResponse, tags=["ai"]
)
def run_arbitration(
    payload: ArbitrateRequest, session: Session = Depends(get_session)
) -> ArbitrationRunResponse:
    """Arbitrate every residual in a run, verify each proposal, induce rules."""
    settings = get_settings()
    resolved = require_run_id(session, payload.run_id)
    arbitrator = get_arbitrator(payload.arbitrator or settings.ai_provider)
    result = arbitration_service.arbitrate_run(
        session,
        resolved,
        arbitrator=arbitrator,
        propose_rules=payload.propose_rules,
        limit=payload.limit,
    )
    return ArbitrationRunResponse(**result)


@router.post(
    "/arbitration/run/{run_id}", response_model=ArbitrationRunResponse, tags=["ai"]
)
def run_arbitration_by_id(
    run_id: str,
    arbitrator_name: Optional[str] = Query(default=None, alias="arbitrator"),
    session: Session = Depends(get_session),
) -> ArbitrationRunResponse:
    """Arbitrate residuals for a specific run ID."""
    settings = get_settings()
    resolved = require_run_id(session, run_id)
    arbitrator = get_arbitrator(arbitrator_name or settings.ai_provider)
    result = arbitration_service.arbitrate_run(
        session,
        resolved,
        arbitrator=arbitrator,
        propose_rules=True,
    )
    return ArbitrationRunResponse(**result)


@router.get(
    "/arbitration/results", response_model=ArbitrationListResponse, tags=["ai"]
)
def list_arbitration(
    run_id: Optional[str] = None,
    decision: Optional[str] = None,
    accepted_only: bool = False,
    limit: int = Query(default=200, ge=1, le=2000),
    session: Session = Depends(get_session),
) -> ArbitrationListResponse:
    resolved = require_run_id(session, run_id)
    stmt = select(ArbitrationRow).where(ArbitrationRow.run_id == resolved)
    if decision:
        stmt = stmt.where(ArbitrationRow.decision == decision.upper())
    if accepted_only:
        stmt = stmt.where(ArbitrationRow.verification_accepted.is_(True))
    rows = list(session.scalars(stmt).all())
    rows.sort(key=lambda r: (-r.amount_paisa, r.residual_id))

    return ArbitrationListResponse(
        run_id=resolved,
        items=[
            {
                "residual_id": r.residual_id,
                "run_id": r.run_id,
                "arbitrator": r.arbitrator,
                "uses_model": r.uses_model,
                "decision": r.decision,
                "confidence": r.confidence,
                "reason": r.reason,
                "proposed_action": r.proposed_action,
                "evidence": r.evidence or [],
                "candidates": r.candidates or [],
                "amount_paisa": r.amount_paisa,
                "verification_accepted": r.verification_accepted,
                "verification_reasons": r.verification_reasons or [],
                "journal_batch": r.journal_batch or {},
                "requires_human_review": r.requires_human_review,
                "created_at": r.created_at,
            }
            for r in rows[:limit]
        ],
        total=len(rows),
        summary=arbitration_service.arbitration_summary(session, resolved),
    )


@router.get(
    "/arbitration/results/{residual_id}", tags=["ai"]
)
def get_arbitration_result(
    residual_id: str, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    row = session.scalar(
        select(ArbitrationRow).where(ArbitrationRow.residual_id == residual_id).order_by(ArbitrationRow.created_at.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Residual {residual_id} arbitration not found")
    return {
        "residual_id": row.residual_id,
        "run_id": row.run_id,
        "arbitrator": row.arbitrator,
        "uses_model": row.uses_model,
        "decision": row.decision,
        "confidence": row.confidence,
        "reason": row.reason,
        "proposed_action": row.proposed_action,
        "evidence": row.evidence or [],
        "candidates": row.candidates or [],
        "amount_paisa": row.amount_paisa,
        "verification_accepted": row.verification_accepted,
        "verification_reasons": row.verification_reasons or [],
        "journal_batch": row.journal_batch or {},
        "requires_human_review": row.requires_human_review,
        "created_at": row.created_at,
    }


@router.post(
    "/arbitration/{residual_id}/approve", tags=["ai"]
)
def approve_arbitration(
    residual_id: str, actor: str = Query(default="human@finance"), session: Session = Depends(get_session)
) -> Dict[str, Any]:
    try:
        row = arbitration_service.approve_residual(session, residual_id, actor=actor)
        return {"status": "success", "residual_id": row.residual_id, "decision": row.decision}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/arbitration/{residual_id}/reject", tags=["ai"]
)
def reject_arbitration(
    residual_id: str, actor: str = Query(default="human@finance"), session: Session = Depends(get_session)
) -> Dict[str, Any]:
    try:
        row = arbitration_service.reject_residual(session, residual_id, actor=actor)
        return {"status": "success", "residual_id": row.residual_id, "decision": row.decision}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/arbitration/{residual_id}/unresolve", tags=["ai"]
)
def unresolve_arbitration(
    residual_id: str, actor: str = Query(default="human@finance"), session: Session = Depends(get_session)
) -> Dict[str, Any]:
    try:
        row = arbitration_service.unresolve_residual(session, residual_id, actor=actor)
        return {"status": "success", "residual_id": row.residual_id, "decision": row.decision}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/arbitration/evaluate/{run_id}", tags=["ai"]
)
def evaluate_arbitration_run(
    run_id: str, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    from app.services.ai.evaluation import evaluate_run_arbitration
    resolved = require_run_id(session, run_id)
    metrics = evaluate_run_arbitration(session, resolved)
    return metrics.to_dict()


@router.get(
    "/arbitration/metrics/{run_id}", tags=["ai"]
)
def get_ai_metrics(
    run_id: str, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    resolved = require_run_id(session, run_id)
    return arbitration_service.arbitration_summary(session, resolved)


# --- rules ----------------------------------------------------------------
def _rule_catalogue(session: Session) -> RuleCatalogueResponse:
    """Shared body, called directly by the decision handlers."""
    rows = list(session.scalars(select(RuleRow).order_by(RuleRow.rule_id)).all())
    by_status: Dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1

    return RuleCatalogueResponse(
        rules=[registry.rule_to_dict(r) for r in rows],
        total=len(rows),
        by_status=by_status,
        active_dynamic_rules=[r.rule_id for r in registry.active_dynamic_rules(session)],
        validations=[
            registry.validation_to_dict(v) for v in registry.validations_for(session)
        ],
        lifecycle=LIFECYCLE,
        note=(
            "Built-in rules are compiled into the engine. Dynamic rules are "
            "induced from arbitration evidence, validated by replay, and reach "
            "ACTIVE only when a named human promotes an APPROVED rule."
        ),
    )


@router.get("/rules", response_model=RuleCatalogueResponse, tags=["rules"])
def list_rules(session: Session = Depends(get_session)) -> RuleCatalogueResponse:
    return _rule_catalogue(session)


@router.post(
    "/rules/{rule_id}/validate", response_model=RuleCatalogueResponse, tags=["rules"]
)
def validate_rule_endpoint(
    rule_id: str,
    payload: RuleValidateRequest,
    session: Session = Depends(get_session),
) -> RuleCatalogueResponse:
    """Replay a candidate rule over a dataset and record the measured effect."""
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"rule {rule_id} not found")
    if not (rule.parameters or {}).get("pattern"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"rule {rule_id} is a built-in compiled into the engine; only a "
                f"dynamic rule can be replayed"
            ),
        )

    dataset_id = payload.dataset_id or rule.parameters.get("dataset_id") or (
        runner.DEFAULT_DATASET_ID
    )
    if not runner.dataset_exists(dataset_id):
        raise HTTPException(status_code=400, detail=f"dataset {dataset_id} not found")

    settings = get_settings()
    report = validate_rule(
        runner.load(dataset_id),
        rule_id,
        rule.parameters,
        validation_id=registry.next_validation_id(session),
        accounting=settings.accounting,
        reconciliation=settings.reconciliation,
        active_rules=[
            r for r in registry.active_reference_rules(session) if r.rule_id != rule_id
        ],
    )
    registry.record_validation(session, rule_id, report)
    return _rule_catalogue(session)


@router.post(
    "/rules/{rule_id}/promote", response_model=RuleCatalogueResponse, tags=["rules"]
)
def promote_rule(
    rule_id: str,
    payload: RuleDecisionRequest,
    session: Session = Depends(get_session),
) -> RuleCatalogueResponse:
    """Activate an APPROVED rule. Requires a named actor; this is the human gate."""
    try:
        registry.promote(session, rule_id, actor=payload.actor, note=payload.note)
    except registry.RulePromotionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _rule_catalogue(session)


@router.post(
    "/rules/{rule_id}/reject", response_model=RuleCatalogueResponse, tags=["rules"]
)
def reject_rule(
    rule_id: str,
    payload: RuleDecisionRequest,
    session: Session = Depends(get_session),
) -> RuleCatalogueResponse:
    try:
        registry.reject(session, rule_id, actor=payload.actor, note=payload.note)
    except registry.RulePromotionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _rule_catalogue(session)


@router.post(
    "/rules/{rule_id}/retire", response_model=RuleCatalogueResponse, tags=["rules"]
)
def retire_rule(
    rule_id: str,
    payload: RuleDecisionRequest,
    session: Session = Depends(get_session),
) -> RuleCatalogueResponse:
    try:
        registry.retire(session, rule_id, actor=payload.actor, note=payload.note)
    except registry.RulePromotionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _rule_catalogue(session)


@router.get("/rules/impact/{rule_id}", tags=["rules"])
def get_rule_impact(
    rule_id: str, session: Session = Depends(get_session)
) -> Dict[str, Any]:
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"rule {rule_id} not found")
    validations = registry.validations_for(session, rule_id)
    latest_val = validations[0] if validations else None

    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "version": rule.version,
        "status": rule.status,
        "created_at": rule.created_at,
        "promoted_at": rule.promoted_at,
        "approved_by": rule.approved_by,
        "occurrence_count": rule.occurrence_count,
        "additional_deterministic_matches": rule.expected_match_gain,
        "false_positives": rule.expected_false_positive_rate,
        "ai_calls_avoided": rule.expected_match_gain,
        "backtest": latest_val.detail if latest_val else {},
    }


@router.post("/rules/demo-scenario", tags=["rules"])
def run_demo_self_healing_scenario(
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """Execute end-to-end self-healing rule promotion demo workflow in under 90s."""
    from app.services.ai.mock_arbitrator import MockResidualArbitrator

    dataset_id = "demo-self-healing"
    # Step 1: Generate dataset
    runner.generate_dataset(
        dataset_id=dataset_id, mode="messy", order_count=500, seed=42
    )

    # Step 2: Run baseline reconciliation
    run_1_res = runner.execute_run(
        session, dataset_id=dataset_id, label="Baseline (Before Rule)"
    )
    run_1_id = run_1_res.run_id
    b_matches = run_1_res.deterministic_matches
    b_residuals = run_1_res.residuals

    # Step 3: Run AI Arbitration
    arbitrator = MockResidualArbitrator()
    arb_res = arbitration_service.arbitrate_run(
        session, run_id=run_1_id, arbitrator=arbitrator, propose_rules=True
    )

    proposals = arb_res.get("rule_proposals", [])
    promoted_rule_id = None
    rule_name = ""

    if proposals:
        prop = proposals[0]
        rule_row, _ = registry.record_proposal(session, prop, run_id=run_1_id)
        promoted_rule_id = rule_row.rule_id
        rule_name = rule_row.name

        # Step 4: Backtest Rule
        report = validate_rule(
            runner.load(dataset_id),
            promoted_rule_id,
            rule_row.parameters,
            validation_id=registry.next_validation_id(session),
            accounting=settings.accounting,
            reconciliation=settings.reconciliation,
            active_rules=[],
        )
        registry.record_validation(session, promoted_rule_id, report)

        # Step 5: Approve & Activate Rule
        registry.promote(
            session,
            promoted_rule_id,
            actor="demo.approver@company.com",
            note="Auto-approved in demo scenario",
        )

    # Step 6: Re-run reconciliation engine with active rule
    run_2_res = runner.execute_run(
        session, dataset_id=dataset_id, label="Self-Healed (After Rule)"
    )
    run_2_id = run_2_res.run_id
    a_matches = run_2_res.deterministic_matches
    a_residuals = run_2_res.residuals

    match_delta = a_matches - b_matches
    ai_reduction_pct = (
        round((1.0 - (a_residuals / max(1, b_residuals))) * 100, 2)
        if b_residuals > 0
        else 0.0
    )

    return {
        "status": "success",
        "dataset_id": dataset_id,
        "baseline_run_id": run_1_id,
        "self_healed_run_id": run_2_id,
        "promoted_rule_id": promoted_rule_id,
        "promoted_rule_name": rule_name,
        "baseline_matches": b_matches,
        "after_matches": a_matches,
        "matches_added": match_delta,
        "baseline_residuals": b_residuals,
        "after_residuals": a_residuals,
        "residual_reduction": b_residuals - a_residuals,
        "ai_dependency_reduction_pct": ai_reduction_pct,
        "deterministic_coverage_before_pct": round((b_matches / 500) * 100, 2),
        "deterministic_coverage_after_pct": round((a_matches / 500) * 100, 2),
        "estimated_ai_cost_avoided_usd": round(match_delta * 0.002, 4),
        "message": f"Successfully activated {promoted_rule_id}! Reduced AI dependency by {ai_reduction_pct}%.",
    }


# --- journals -------------------------------------------------------------
def _journal_payload(
    session: Session,
    run_id: Optional[str],
    status: Optional[str] = None,
    residual_id: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> JournalListResponse:
    """Shared body. Kept out of the route so other handlers can reuse it.

    Calling a FastAPI route function directly leaves its Query() defaults
    unresolved, so anything that needs this payload calls the plain function.
    """
    resolved = repo.resolve_run_id(session, run_id)
    rows, total = posting.list_entries(
        session,
        run_id=resolved,
        status=status,
        residual_id=residual_id,
        limit=limit,
        offset=offset,
    )
    all_rows, _ = posting.list_entries(session, run_id=resolved, limit=100_000)
    by_status: Dict[str, int] = {}
    for row in all_rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1

    return JournalListResponse(
        entries=[posting.entry_to_dict(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        by_status=by_status,
        total_proposed_paisa=sum(
            r.amount_paisa for r in all_rows if r.status == "PROPOSED"
        ),
        chart_of_accounts=coa.all_accounts(),
    )


@router.get("/journal", response_model=JournalListResponse, tags=["accounting"])
def list_journal(
    run_id: Optional[str] = None,
    status: Optional[str] = None,
    residual_id: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> JournalListResponse:
    return _journal_payload(session, run_id, status, residual_id, limit, offset)


@router.post(
    "/journal/{journal_id}/decide",
    response_model=JournalListResponse,
    tags=["accounting"],
)
def decide_journal(
    journal_id: str,
    payload: JournalDecisionRequest,
    session: Session = Depends(get_session),
) -> JournalListResponse:
    """Approve, reject or post one entry. Posting re-verifies the batch."""
    try:
        row = posting.decide(
            session,
            journal_id,
            decision=payload.decision,
            actor=payload.actor,
            note=payload.note,
        )
    except posting.PostingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journal_payload(session, row.run_id)


@router.get(
    "/journal/trial-balance", response_model=TrialBalanceResponse, tags=["accounting"]
)
def get_trial_balance(
    run_id: Optional[str] = None, session: Session = Depends(get_session)
) -> TrialBalanceResponse:
    """Balances from POSTED entries only. Proposals are excluded by design."""
    resolved = repo.resolve_run_id(session, run_id)
    return TrialBalanceResponse(**posting.trial_balance(session, resolved))


# --- forecasting ----------------------------------------------------------
@router.get("/cash-position/forecast", response_model=ForecastResponse, tags=["cash"])
def get_forecast(
    run_id: Optional[str] = None,
    horizon_days: int = Query(default=30, ge=1, le=180),
    session: Session = Depends(get_session),
) -> ForecastResponse:
    """Committed pipeline plus a backtested run-rate band."""
    settings = get_settings()
    resolved = require_run_id(session, run_id)
    rows = list(
        session.scalars(
            select(ReconciliationRecord).where(
                ReconciliationRecord.run_id == resolved
            )
        ).all()
    )

    daily: Dict[date, int] = {}
    committed: List[tuple] = []
    for row in rows:
        if row.status == "MATCHED" and row.value_date:
            daily[row.value_date] = daily.get(row.value_date, 0) + row.actual_amount_paisa
        elif row.status == "PARTIAL_MATCH":
            committed.append(
                (row.value_date, row.expected_amount_paisa, list(row.settlement_ids or []))
            )

    history = [DailyObservation(day=d, amount_paisa=v) for d, v in sorted(daily.items())]
    forecaster = SettlementCycleForecaster(
        expected_lag_days=settings.reconciliation.expected_settlement_lag_days
    )
    result = forecaster.forecast(horizon_days, history, committed=committed)
    payload = result.to_dict()

    note = (
        "Committed lines are exact amounts from proved settlements; only their "
        "landing date is projected. The band is empirical and its confidence is "
        "backtested on held-out history, not asserted."
    )
    if result.backtest and not result.backtest.usable:
        note = result.backtest.note + " Only the committed pipeline is projected."

    return ForecastResponse(run_id=resolved, note=note, **payload)


@router.get("/cash-position/resilience", response_model=CashResilienceResponse, tags=["cash"])
def get_cash_resilience(
    run_id: Optional[str] = None,
    session: Session = Depends(get_session),
) -> CashResilienceResponse:
    """Deterministic 13-week Cash Resilience Controller projection."""
    from app.services.forecasting.resilience_forecaster import build_13week_resilience_forecast
    resolved = require_run_id(session, run_id)

    matched, _ = repo.query_records(session, resolved, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(session, resolved, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(session, resolved, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)

    forecast = build_13week_resilience_forecast(matched, partial, exceptions)
    payload = forecast.to_dict()

    return CashResilienceResponse(
        run_id=resolved,
        note="13-week cash resilience controller derived strictly from reconciled records.",
        **payload,
    )


# --- copilot --------------------------------------------------------------
@router.post("/copilot/ask", response_model=CopilotResponse, tags=["ai"])
def copilot_ask(
    payload: CopilotRequest, session: Session = Depends(get_session)
) -> CopilotResponse:
    """Answer from stored facts with evidence verification gate & audit logging."""
    from app.services.ai.evidence_verifier import verify_copilot_evidence
    from app.models.entities import CopilotQueryAuditRow
    import uuid

    answer = answer_question(session, payload.question, payload.run_id)
    verification = verify_copilot_evidence(
        session,
        answer.answer,
        answer.facts,
        answer.records,
        run_id=payload.run_id,
    )

    if not verification.passed and answer.intent != "UNKNOWN":
        answer.answer = "I couldn't verify this answer from the available financial records."
        answer.grounded = False
        answer.confidence = 0.0
        answer.confidence_method = "REJECTED_BY_GATE"

    # Audit log material query
    try:
        audit_row = CopilotQueryAuditRow(
            query_id=f"COP-{uuid.uuid4().hex[:12]}",
            run_id=payload.run_id,
            question=payload.question,
            intent=answer.intent,
            answer=answer.answer,
            confidence=answer.confidence,
            confidence_method=answer.confidence_method,
            facts=answer.facts,
            citations=answer.citations,
            verification_passed=verification.passed,
            actor="finance_copilot",
            created_at=datetime.now(),
        )
        session.add(audit_row)
        session.commit()
    except Exception:
        session.rollback()

    return CopilotResponse(**answer.to_dict())


@router.get("/reconciliation/runs/compare", tags=["reconciliation"])
def compare_runs_endpoint(
    baseline: str = Query(description="Baseline run_id"),
    candidate: str = Query(description="Candidate run_id"),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Calculate exact deltas between two reconciliation runs."""
    base_run = repo.get_run(session, baseline)
    cand_run = repo.get_run(session, candidate)
    if not base_run or not cand_run:
        raise HTTPException(status_code=404, detail="One or both runs not found")

    match_delta = cand_run.deterministic_matches - base_run.deterministic_matches
    residuals_delta = cand_run.residuals - base_run.residuals
    unexplained_delta = cand_run.unexplained_value_paisa - base_run.unexplained_value_paisa
    match_rate_delta = cand_run.match_rate - base_run.match_rate

    return {
        "baseline_run_id": baseline,
        "candidate_run_id": candidate,
        "deterministic_matches_baseline": base_run.deterministic_matches,
        "deterministic_matches_candidate": cand_run.deterministic_matches,
        "deterministic_matches_delta": match_delta,
        "residuals_baseline": base_run.residuals,
        "residuals_candidate": cand_run.residuals,
        "residuals_delta": residuals_delta,
        "unexplained_value_baseline_paisa": base_run.unexplained_value_paisa,
        "unexplained_value_candidate_paisa": cand_run.unexplained_value_paisa,
        "unexplained_value_delta_paisa": unexplained_delta,
        "match_rate_baseline": base_run.match_rate,
        "match_rate_candidate": cand_run.match_rate,
        "match_rate_delta_pp": round(match_rate_delta * 100, 2),
    }


@router.post("/demo/full-sequence", tags=["demo"])
def run_full_demo_sequence(
    session: Session = Depends(get_session)
) -> Dict[str, Any]:
    """Execute complete 60-second hackathon demo sequence from start to finish."""
    # 1. Run demo self-healing scenario
    demo_res = run_demo_self_healing_scenario(session)
    run_id = demo_res["self_healed_run_id"]

    # 2. Get cash resilience
    matched, _ = repo.query_records(session, run_id, statuses=["MATCHED"], limit=10000)
    partial, _ = repo.query_records(session, run_id, statuses=["PARTIAL_MATCH"], limit=10000)
    exceptions, _ = repo.query_records(session, run_id, statuses=repo.EXCEPTION_DESK_STATUSES, limit=10000)
    from app.services.forecasting.resilience_forecaster import build_13week_resilience_forecast
    resilience = build_13week_resilience_forecast(matched, partial, exceptions)

    # 3. Answer payroll question
    copilot_ans = answer_question(session, "Will we meet payroll next Friday?", run_id)

    return {
        "status": "success",
        "demo_self_healing": demo_res,
        "run_id": run_id,
        "resilience_summary": {
            "current_cash_paisa": resilience.current_cash_paisa,
            "outlook_13w_paisa": resilience.outlook_13w_paisa,
            "at_risk_cash_paisa": resilience.at_risk_cash_paisa,
            "payroll_risk_level": resilience.payroll_risk.risk_level,
        },
        "copilot_payroll_answer": copilot_ans.to_dict(),
    }


@router.get("/accounting/chart", tags=["accounting"])
def get_chart_of_accounts() -> Dict[str, Any]:
    """The accounts a proposal may name. Anything else is rejected."""
    return {"accounts": coa.all_accounts(), "total": len(coa.ACCOUNTS)}
