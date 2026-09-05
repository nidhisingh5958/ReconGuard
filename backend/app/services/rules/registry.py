"""Rule registry and promotion lifecycle.

The lifecycle is deliberately split so that the safe half is automatic and the
consequential half is not:

    PROPOSED   -> induced from arbitration evidence
    VALIDATING -> replayed against a dataset; measurement is automatic, because
                  measuring is safe and a human reading numbers off a screen adds
                  nothing to their reliability
    APPROVED   -> the replay improved matching with zero regressions
    REJECTED   -> the replay regressed, was neutral, or the rule was unsafe
    ACTIVE     -> a named human promoted it; this is the only transition that
                  changes what the engine does, so it is the one that requires
                  a person
    RETIRED    -> superseded or withdrawn

``promote`` refuses anything not APPROVED and demands an actor. That is the
whole safety argument: a rule cannot reach production without evidence from a
replay AND a named person, and every transition is auditable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AuditAction, RuleStatus
from app.models.entities import AuditEventRow, RuleRow, RuleValidationRow
from app.services.rules.dynamic import (
    AmountToleranceRule,
    DateToleranceRule,
    DynamicRuleSet,
    ReferenceExtractionRule,
    RuleType,
    validate_dynamic_rule_params,
)
from app.services.rules.proposal import RuleProposal
from app.services.rules.validator import ValidationReport


class RulePromotionError(RuntimeError):
    """Raised when a lifecycle transition is not permitted."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_rule_audit_event(
    session: Session,
    action: str,
    actor: str,
    rule_id: str,
    previous_state: Optional[str],
    new_state: Optional[str],
    run_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> None:
    event = AuditEventRow(
        audit_id=f"AUD-RULE-{int(datetime.now(timezone.utc).timestamp()*1000)}",
        run_id=run_id,
        timestamp=_now(),
        action=action,
        actor=actor,
        rule_id=rule_id,
        calculation="",
        previous_state=previous_state,
        new_state=new_state,
        detail=detail or {},
        system_version="1.0.0",
    )
    session.add(event)


def next_rule_id(session: Session, prefix: str = "RULE-DYN") -> str:
    existing = {
        row[0]
        for row in session.execute(
            select(RuleRow.rule_id).where(RuleRow.rule_id.like(f"{prefix}-%"))
        ).all()
    }
    n = 1
    while f"{prefix}-{n:03d}" in existing:
        n += 1
    return f"{prefix}-{n:03d}"


def next_validation_id(session: Session) -> str:
    count = len(session.execute(select(RuleValidationRow.id)).all())
    return f"VAL-{count + 1:05d}"


def find_equivalent(session: Session, proposal: RuleProposal) -> Optional[RuleRow]:
    """Return an existing rule with the same pattern, if any."""
    for row in session.scalars(
        select(RuleRow).where(RuleRow.rule_type == proposal.rule_type)
    ).all():
        params = row.parameters or {}
        if proposal.rule_type == RuleType.REFERENCE_EXTRACTION:
            if params.get("pattern") == proposal.pattern and params.get("marker") == proposal.marker:
                return row
        elif proposal.rule_type == RuleType.AMOUNT_TOLERANCE:
            if params.get("gateway") == proposal.marker:
                return row
    return None


def record_proposal(
    session: Session,
    proposal: RuleProposal,
    run_id: str,
    created_by: str = "arbitrator",
) -> Tuple[RuleRow, bool]:
    """Persist a proposal. Returns ``(row, created)``; idempotent by pattern."""
    existing = find_equivalent(session, proposal)
    if existing is not None:
        return existing, False

    row = RuleRow(
        rule_id=next_rule_id(session),
        name=proposal.name,
        description=proposal.description,
        rule_type=proposal.rule_type,
        expression=proposal.expression,
        version=1,
        status=RuleStatus.PROPOSED.value,
        created_by=created_by,
        created_at=_now(),
        updated_at=_now(),
        validation_count=0,
        parameters=proposal.parameters(),
        proposed_from_run=run_id,
        supporting_residuals=list(proposal.supporting_residuals),
        occurrence_count=len(proposal.supporting_residuals),
        decision_note=(
            f"Induced from {proposal.support} independent arbitration pairings."
        ),
    )
    session.add(row)
    _log_rule_audit_event(
        session,
        action="RULE_PROPOSED",
        actor=created_by,
        rule_id=row.rule_id,
        previous_state=None,
        new_state=RuleStatus.PROPOSED.value,
        detail={"proposed_from_run": run_id, "support": proposal.support},
    )
    session.commit()
    return row, True


def record_validation(
    session: Session, rule_id: str, report: ValidationReport
) -> RuleValidationRow:
    """Store a replay result and move the rule to APPROVED or REJECTED."""
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise RulePromotionError(f"rule {rule_id} not found")

    row = RuleValidationRow(
        validation_id=report.validation_id,
        rule_id=rule_id,
        dataset_id=report.dataset_id,
        baseline_matches=report.baseline_matches,
        candidate_matches=report.candidate_matches,
        match_delta=report.match_delta,
        baseline_residuals=report.baseline_residuals,
        candidate_residuals=report.candidate_residuals,
        residual_delta=report.residual_delta,
        baseline_match_rate=report.baseline_match_rate,
        candidate_match_rate=report.candidate_match_rate,
        regressions=list(report.regressions),
        verdict=report.verdict,
        detail=dict(report.detail),
        created_at=_now(),
    )
    session.add(row)

    prev_status = rule.status
    rule.validation_count = (rule.validation_count or 0) + 1
    rule.updated_at = _now()
    rule.backtest_result = report.to_dict()
    rule.expected_match_gain = max(0, report.match_delta)
    rule.expected_false_positive_rate = float(len(report.regressions))

    if report.approved:
        rule.status = RuleStatus.APPROVED.value
        rule.decision_note = (
            f"Replay over {report.dataset_id} moved {report.match_delta} records into "
            f"MATCHED with no regressions "
            f"({report.match_rate_delta_pct:+.2f}pp match rate). "
            f"Awaiting human promotion."
        )
    else:
        rule.status = RuleStatus.REJECTED.value
        detail = (
            f"{len(report.regressions)} regression(s)"
            if report.regressions
            else f"match delta {report.match_delta}"
        )
        rule.decision_note = (
            f"Replay over {report.dataset_id} did not justify promotion: "
            f"{report.verdict.lower()} ({detail})."
        )

    _log_rule_audit_event(
        session,
        action="RULE_BACKTESTED",
        actor="system",
        rule_id=rule_id,
        previous_state=prev_status,
        new_state=rule.status,
        detail={"verdict": report.verdict, "match_delta": report.match_delta},
    )

    session.commit()
    return row


def promote(session: Session, rule_id: str, actor: str, note: str = "") -> RuleRow:
    """Activate an APPROVED rule. The only transition that needs a human."""
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise RulePromotionError(f"rule {rule_id} not found")
    if not actor or not actor.strip():
        raise RulePromotionError(
            "promotion requires a named actor; an unattributed change to what the "
            "engine matches is not auditable"
        )
    if rule.status != RuleStatus.APPROVED.value:
        raise RulePromotionError(
            f"rule {rule_id} is {rule.status}; only an APPROVED rule may be "
            f"promoted, and approval requires a replay that improved matching "
            f"with no regressions"
        )
    problems = validate_dynamic_rule_params(rule.rule_type, rule.parameters or {})
    if problems:
        raise RulePromotionError(
            f"rule {rule_id} no longer passes safety validation: {problems}"
        )

    prev_status = rule.status
    rule.status = RuleStatus.ACTIVE.value
    rule.promoted_at = _now()
    rule.approved_at = _now()
    rule.approved_by = actor
    rule.updated_at = _now()
    rule.created_by = rule.created_by or "arbitrator"
    rule.decision_note = (
        f"Promoted to ACTIVE by {actor}." + (f" {note}" if note else "")
    )
    _log_rule_audit_event(
        session,
        action="RULE_ACTIVATED",
        actor=actor,
        rule_id=rule_id,
        previous_state=prev_status,
        new_state=RuleStatus.ACTIVE.value,
        detail={"note": note},
    )
    session.commit()
    return rule


def reject(session: Session, rule_id: str, actor: str, note: str = "") -> RuleRow:
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise RulePromotionError(f"rule {rule_id} not found")
    prev_status = rule.status
    rule.status = RuleStatus.REJECTED.value
    rule.updated_at = _now()
    rule.decision_note = f"Rejected by {actor}." + (f" {note}" if note else "")
    _log_rule_audit_event(
        session,
        action="RULE_REJECTED",
        actor=actor,
        rule_id=rule_id,
        previous_state=prev_status,
        new_state=RuleStatus.REJECTED.value,
        detail={"note": note},
    )
    session.commit()
    return rule


def retire(session: Session, rule_id: str, actor: str, note: str = "") -> RuleRow:
    rule = session.get(RuleRow, rule_id)
    if rule is None:
        raise RulePromotionError(f"rule {rule_id} not found")
    if rule.status != RuleStatus.ACTIVE.value:
        raise RulePromotionError(f"rule {rule_id} is {rule.status}, not ACTIVE")
    prev_status = rule.status
    rule.status = RuleStatus.RETIRED.value
    rule.updated_at = _now()
    rule.decision_note = f"Retired by {actor}." + (f" {note}" if note else "")
    _log_rule_audit_event(
        session,
        action="RULE_RETIRED",
        actor=actor,
        rule_id=rule_id,
        previous_state=prev_status,
        new_state=RuleStatus.RETIRED.value,
        detail={"note": note},
    )
    session.commit()
    return rule


def active_dynamic_rules(session: Session) -> List[RuleRow]:
    """ACTIVE rules that carry executable parameters."""
    rows = session.scalars(
        select(RuleRow).where(RuleRow.status == RuleStatus.ACTIVE.value)
    ).all()
    return list(rows)


def load_rule_set(session: Session) -> Optional[DynamicRuleSet]:
    """Build the DynamicRuleSet the engine should run with, or None."""
    rows = active_dynamic_rules(session)
    if not rows:
        return None
    rule_set = DynamicRuleSet.from_rows(rows)
    return rule_set or None


def active_reference_rules(session: Session) -> List[ReferenceExtractionRule]:
    """Promoted reference rules, for validating a candidate on top of them."""
    rule_set = load_rule_set(session)
    return list(rule_set.reference_rules) if rule_set else []


def validations_for(
    session: Session, rule_id: Optional[str] = None
) -> List[RuleValidationRow]:
    stmt = select(RuleValidationRow)
    if rule_id:
        stmt = stmt.where(RuleValidationRow.rule_id == rule_id)
    rows = list(session.scalars(stmt).all())
    rows.sort(key=lambda r: r.created_at, reverse=True)
    return rows


def rule_to_dict(row: RuleRow) -> Dict[str, Any]:
    return {
        "rule_id": row.rule_id,
        "name": row.name,
        "description": row.description,
        "rule_type": row.rule_type,
        "expression": row.expression,
        "version": row.version,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "validation_count": row.validation_count,
        "promoted_at": row.promoted_at,
        "parameters": row.parameters or {},
        "proposed_from_run": row.proposed_from_run,
        "supporting_residuals": row.supporting_residuals or [],
        "decision_note": row.decision_note or "",
        "updated_at": row.updated_at,
        "is_dynamic": bool((row.parameters or {}).get("pattern")),
    }


def validation_to_dict(row: RuleValidationRow) -> Dict[str, Any]:
    return {
        "validation_id": row.validation_id,
        "rule_id": row.rule_id,
        "dataset_id": row.dataset_id,
        "baseline_matches": row.baseline_matches,
        "candidate_matches": row.candidate_matches,
        "match_delta": row.match_delta,
        "baseline_residuals": row.baseline_residuals,
        "candidate_residuals": row.candidate_residuals,
        "residual_delta": row.residual_delta,
        "baseline_match_rate": row.baseline_match_rate,
        "candidate_match_rate": row.candidate_match_rate,
        "match_rate_delta_pct": round(
            (row.candidate_match_rate - row.baseline_match_rate) * 100, 4
        ),
        "regressions": row.regressions or [],
        "verdict": row.verdict,
        "detail": row.detail or {},
        "created_at": row.created_at,
    }
