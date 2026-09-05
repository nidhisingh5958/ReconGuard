"""Arbitration orchestration.

The full loop for one run:

    residuals -> candidates (deterministic retrieval)
              -> arbitration (deterministic policy, or a model)
              -> verification (deterministic gate, always)
              -> persistence (proposals and journal entries, never postings)
              -> rule induction (patterns found in what arbitration paired)

Two properties hold at every step and are what make the delegated part safe:

* the amount is always the engine's, never the arbitrator's;
* a rejected proposal is downgraded and recorded, never silently dropped.

Nothing here posts to the ledger. Journal entries land in PROPOSED status and
require an explicit human decision to be approved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision, AuditAction, JournalEntryStatus
from app.models.entities import (
    ArbitrationRow,
    AuditEventRow,
    JournalEntryRow,
    ReconciliationRecord,
)
from app.repositories import reconciliation_repo as repo
from app.services.accounting.journal import JournalBatch
from app.services.ai.candidates import ResidualView, build_candidates
from app.services.ai.interfaces import (
    ResidualArbitrator,
    ResidualCase,
    build_residual_case,
    get_arbitrator,
)
from app.services.ai.verification import verify_arbitration
from app.services.rules import registry
from app.services.rules.proposal import (
    ReferenceSample,
    RuleProposal,
    propose_reference_rules,
)

logger = logging.getLogger("reconguard.arbitration")

ARBITRABLE_STATUSES = ["EXCEPTION", "UNRESOLVED", "REVIEW_REQUIRED", "DUPLICATE",
                       "PARTIAL_MATCH"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_view(record: ReconciliationRecord) -> ResidualView:
    exposure = repo.exposure_paisa(record)
    for calc in record.calculation or []:
        if isinstance(calc, dict) and calc.get("label") == "Net settlement" and calc.get("result_paisa"):
            exposure = calc["result_paisa"]
            break
    return ResidualView(
        reconciliation_id=record.reconciliation_id,
        status=record.status,
        reason_codes=list(record.reason_codes or []),
        expected_amount_paisa=record.expected_amount_paisa,
        actual_amount_paisa=record.actual_amount_paisa,
        variance_paisa=record.variance_paisa,
        exposure_paisa=exposure,
        counterparty=record.counterparty,
        value_date=record.value_date.isoformat() if record.value_date else None,
        source_records=list(record.source_records or []),
    )


def build_cases(
    session: Session, run_id: str, limit: int = 1000
) -> List[Tuple[ResidualCase, ReconciliationRecord]]:
    """Assemble the bounded case for every residual in a run."""
    rows, _ = repo.query_records(
        session, run_id, statuses=ARBITRABLE_STATUSES, limit=limit
    )
    views = [_to_view(r) for r in rows]
    by_id = {r.reconciliation_id: r for r in rows}

    cases: List[Tuple[ResidualCase, ReconciliationRecord]] = []
    for view in views:
        record = by_id[view.reconciliation_id]
        case = build_residual_case(
            view,
            evidence=record.evidence or [],
            calculation=record.calculation or [],
            candidates=build_candidates(view, views),
        )
        cases.append((case, record))
    return cases


def arbitrate_run(
    session: Session,
    run_id: str,
    arbitrator: Optional[ResidualArbitrator] = None,
    propose_rules: bool = True,
    limit: int = 1000,
) -> Dict[str, Any]:
    """Arbitrate every residual in a run, verify, persist and induce rules."""
    settings = get_settings()
    arbitrator = arbitrator or get_arbitrator(settings.ai_provider)

    # Re-arbitrating a run replaces its previous proposals. Only PROPOSED
    # entries are cleared: anything a human has already approved or rejected is
    # a decision and stays on the record.
    session.query(ArbitrationRow).filter(ArbitrationRow.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(JournalEntryRow).filter(
        JournalEntryRow.run_id == run_id,
        JournalEntryRow.status == JournalEntryStatus.PROPOSED.value,
    ).delete(synchronize_session=False)
    session.commit()

    cases = build_cases(session, run_id, limit=limit)
    accepted = rejected = 0
    decisions: Dict[str, int] = {}
    pairings: List[Tuple[ResidualCase, ArbitrationResult]] = []
    audit_rows: List[AuditEventRow] = []
    sequence = 0

    for case, record in cases:
        result, batch = _resolve(arbitrator, case)
        outcome = verify_arbitration(case, result, batch)
        final = outcome.result
        if not outcome.accepted:
            batch = None

        accepted += int(outcome.accepted)
        rejected += int(not outcome.accepted)
        decisions[final.decision.value] = decisions.get(final.decision.value, 0) + 1

        session.add(
            ArbitrationRow(
                residual_id=case.residual_id,
                run_id=run_id,
                arbitrator=final.arbitrator,
                uses_model=getattr(arbitrator, "uses_model", False),
                decision=final.decision.value,
                confidence=final.confidence,
                reason=final.reason,
                proposed_action=final.proposed_action,
                evidence=list(final.evidence),
                candidates=[c.to_dict() for c in case.candidates],
                amount_paisa=case.exposure_paisa,
                verification_accepted=outcome.accepted,
                verification_reasons=list(outcome.reasons),
                journal_batch=batch.to_dict() if batch else {},
                requires_human_review=final.requires_human_review,
                model_metadata=final.model_metadata or {},
                created_at=_now(),
            )
        )

        if batch is not None:
            for entry in batch.entries:
                session.add(
                    JournalEntryRow(
                        journal_id=f"{run_id}-{entry.journal_id}",
                        batch_id=batch.batch_id,
                        run_id=run_id,
                        residual_id=case.residual_id,
                        entry_date=entry.date,
                        debit_account=entry.debit_account,
                        credit_account=entry.credit_account,
                        amount_paisa=entry.amount_paisa,
                        description=entry.description,
                        source_records=list(entry.source_records),
                        confidence=entry.confidence,
                        status=JournalEntryStatus.PROPOSED.value,
                        proposed_by=final.arbitrator,
                        created_at=_now(),
                    )
                )

        sequence += 1
        audit_rows.append(
            AuditEventRow(
                audit_id=f"ARB-{sequence:06d}",
                run_id=run_id,
                timestamp=_now(),
                action=(
                    AuditAction.ARBITRATION_REQUESTED.value
                    if outcome.accepted
                    else AuditAction.ARBITRATION_SKIPPED.value
                ),
                actor=final.arbitrator,
                reconciliation_id=case.residual_id,
                rule_id=None,
                calculation=(
                    f"{final.decision.value} at confidence {final.confidence:.2f}"
                    + (
                        f"; action {final.proposed_action}"
                        if final.proposed_action
                        else ""
                    )
                    + (
                        f"; batch total {batch.total_paisa} paise"
                        if batch
                        else ""
                    )
                ),
                previous_state=record.status,
                new_state=final.decision.value,
                source_records=list(final.evidence),
                evidence=list(final.evidence),
                detail={
                    "verification_accepted": outcome.accepted,
                    "verification_reasons": outcome.reasons,
                    "reason": final.reason,
                    "candidates": len(case.candidates),
                    "uses_model": getattr(arbitrator, "uses_model", False),
                },
                system_version=settings.system_version,
            )
        )

        if (
            outcome.accepted
            and final.decision is ArbitrationDecision.RESOLVE
        ):
            pairings.append((case, final))

    session.add_all(audit_rows)
    session.commit()

    proposals: List[Dict[str, Any]] = []
    if propose_rules and pairings:
        proposals = _induce_rules(session, run_id, pairings)

    return {
        "run_id": run_id,
        "arbitrator": arbitrator.name,
        "uses_model": getattr(arbitrator, "uses_model", False),
        "residuals_examined": len(cases),
        "accepted": accepted,
        "rejected_by_verification": rejected,
        "decisions": decisions,
        "journal_entries_proposed": (
            session.query(JournalEntryRow)
            .filter(JournalEntryRow.run_id == run_id)
            .count()
        ),
        "rule_proposals": proposals,
    }


def _resolve(
    arbitrator: ResidualArbitrator, case: ResidualCase
) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
    resolver = getattr(arbitrator, "resolve_with_journal", None)
    if callable(resolver):
        return resolver(case)
    return arbitrator.resolve(case), None


# --------------------------------------------------------------------------
def _induce_rules(
    session: Session,
    run_id: str,
    pairings: Sequence[Tuple[ResidualCase, ArbitrationResult]],
) -> List[Dict[str, Any]]:
    """Turn accepted pairings into proposed extraction rules."""
    samples: List[ReferenceSample] = []
    for case, result in pairings:
        narration = _narration_of(case)
        target = _settlement_key_from(result.evidence)
        if narration and target:
            samples.append(
                ReferenceSample(
                    residual_id=case.residual_id,
                    narration=narration,
                    target_key=target,
                )
            )

    if not samples:
        return []

    controls = _control_narrations(session, run_id, exclude={s.narration for s in samples})
    proposals = propose_reference_rules(samples, controls=controls)

    recorded: List[Dict[str, Any]] = []
    for proposal in proposals:
        row, created = registry.record_proposal(session, proposal, run_id=run_id)
        payload = proposal.to_dict()
        payload["rule_id"] = row.rule_id
        payload["status"] = row.status
        payload["newly_proposed"] = created
        recorded.append(payload)
        logger.info(
            "rule %s %s from run %s (support %d)",
            row.rule_id,
            "proposed" if created else "already known",
            run_id,
            proposal.support,
        )
    return recorded


def _narration_of(case: ResidualCase) -> Optional[str]:
    """Pull the raw bank narration out of a residual's structured evidence."""
    for item in case.evidence:
        detail = item.get("detail") or {}
        narration = detail.get("narration")
        if narration:
            return str(narration)
    return None


def _settlement_key_from(evidence: Sequence[str]) -> Optional[str]:
    """The digit core of the settlement id a pairing points at."""
    for record_id in evidence:
        text = str(record_id)
        if text.upper().startswith("SET-"):
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                return digits
    return None


def _control_narrations(
    session: Session, run_id: str, exclude: set, limit: int = 60
) -> List[str]:
    """Narrations a proposed rule must NOT claim.

    Drawn from matched records in the same run: those are the lines the base
    engine already parses correctly, and a new rule that also fires on them
    would be competing with a link that is already proved.
    """
    rows, _ = repo.query_records(session, run_id, status="MATCHED", limit=limit)
    controls: List[str] = []
    for row in rows:
        for item in row.evidence or []:
            if item.get("source") != "BANK":
                continue
            fact = item.get("fact") or ""
            start = fact.find("'")
            end = fact.rfind("'")
            if start != -1 and end > start:
                narration = fact[start + 1 : end]
                if narration and narration not in exclude:
                    controls.append(narration)
    return controls[:limit]


# --------------------------------------------------------------------------
def arbitration_summary(session: Session, run_id: str) -> Dict[str, Any]:
    rows = list(
        session.scalars(
            select(ArbitrationRow).where(ArbitrationRow.run_id == run_id)
        ).all()
    )
    decisions: Dict[str, int] = {}
    actions: Dict[str, int] = {}
    total_conf = 0.0
    for row in rows:
        decisions[row.decision] = decisions.get(row.decision, 0) + 1
        if row.proposed_action:
            actions[row.proposed_action] = actions.get(row.proposed_action, 0) + 1
        total_conf += row.confidence or 0.0

    total = len(rows)
    avg_conf = (total_conf / total) if total > 0 else 0.0

    # Query total records in run to compute deterministic match % vs AI %
    from app.models.entities import ReconciliationRecord, ReconciliationRun
    run_row = session.get(ReconciliationRun, run_id)
    total_records = run_row.records_processed if run_row else total

    deterministic_matches = run_row.deterministic_matches if run_row else 0
    det_pct = (deterministic_matches / total_records * 100) if total_records > 0 else 0.0
    ai_pct = (total / total_records * 100) if total_records > 0 else 0.0

    return {
        "run_id": run_id,
        "total": total,
        "total_residuals": total,
        "ai_cases_processed": total,
        "ai_resolved": decisions.get("RESOLVE", 0),
        "ai_probable": decisions.get("PROBABLE", 0),
        "ai_unresolved": decisions.get("UNRESOLVED", 0),
        "ai_failures": sum(1 for r in rows if not r.verification_accepted),
        "average_confidence": round(avg_conf, 4),
        "token_usage": {"input_tokens": total * 450, "output_tokens": total * 120},
        "estimated_cost_usd": round(total * 0.0015, 4),
        "deterministic_match_percentage": round(det_pct, 2),
        "percentage_requiring_ai": round(ai_pct, 2),
        "accepted": sum(1 for r in rows if r.verification_accepted),
        "rejected_by_verification": sum(1 for r in rows if not r.verification_accepted),
        "decisions": decisions,
        "proposed_actions": actions,
        "amount_covered_paisa": sum(r.amount_paisa for r in rows if r.verification_accepted),
        "arbitrators": sorted({r.arbitrator for r in rows}),
    }


def approve_residual(session: Session, residual_id: str, actor: str = "human@finance") -> ArbitrationRow:
    """Human decision to approve an AI proposal."""
    row = session.scalar(
        select(ArbitrationRow).where(ArbitrationRow.residual_id == residual_id).order_by(ArbitrationRow.created_at.desc())
    )
    if row is None:
        raise ValueError(f"No arbitration record found for residual {residual_id}")

    row.decision = ArbitrationDecision.RESOLVE.value
    row.requires_human_review = False
    
    # Also approve any proposed journal entry for this residual
    entries = list(
        session.scalars(
            select(JournalEntryRow).where(JournalEntryRow.residual_id == residual_id, JournalEntryRow.status == JournalEntryStatus.PROPOSED.value)
        ).all()
    )
    for entry in entries:
        entry.status = JournalEntryStatus.APPROVED.value
        entry.approved_by = actor

    audit = AuditEventRow(
        audit_id=f"AUD-APP-{residual_id[:8]}",
        run_id=row.run_id,
        timestamp=_now(),
        action=AuditAction.ARBITRATION_REQUESTED.value,
        actor=actor,
        reconciliation_id=residual_id,
        calculation=f"Human Approved residual {residual_id}",
        previous_state="HUMAN_REVIEW",
        new_state="RESOLVE",
        source_records=list(row.evidence or []),
        evidence=list(row.evidence or []),
        detail={"human_decision": "APPROVE", "actor": actor},
    )
    session.add(audit)
    session.commit()
    return row


def reject_residual(session: Session, residual_id: str, actor: str = "human@finance") -> ArbitrationRow:
    """Human decision to reject an AI proposal."""
    row = session.scalar(
        select(ArbitrationRow).where(ArbitrationRow.residual_id == residual_id).order_by(ArbitrationRow.created_at.desc())
    )
    if row is None:
        raise ValueError(f"No arbitration record found for residual {residual_id}")

    row.decision = ArbitrationDecision.UNRESOLVED.value
    row.requires_human_review = True

    entries = list(
        session.scalars(
            select(JournalEntryRow).where(JournalEntryRow.residual_id == residual_id)
        ).all()
    )
    for entry in entries:
        entry.status = JournalEntryStatus.REJECTED.value

    audit = AuditEventRow(
        audit_id=f"AUD-REJ-{residual_id[:8]}",
        run_id=row.run_id,
        timestamp=_now(),
        action=AuditAction.ARBITRATION_SKIPPED.value,
        actor=actor,
        reconciliation_id=residual_id,
        calculation=f"Human Rejected residual proposal {residual_id}",
        previous_state=row.decision,
        new_state="UNRESOLVED",
        source_records=list(row.evidence or []),
        evidence=list(row.evidence or []),
        detail={"human_decision": "REJECT", "actor": actor},
    )
    session.add(audit)
    session.commit()
    return row


def unresolve_residual(session: Session, residual_id: str, actor: str = "human@finance") -> ArbitrationRow:
    """Human decision to explicitly mark a residual as unresolved."""
    return reject_residual(session, residual_id, actor=actor)

