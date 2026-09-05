"""The verification gate.

This is the "Verified AI" half of the product. Every arbitration proposal,
whatever produced it, passes through here before it can influence anything. The
gate weighs arithmetic and provenance. It does not weigh the confidence the
proposer asserted, because a confident wrong answer is the failure mode this
whole system exists to prevent.

A proposal is rejected when it:

* claims RESOLVE without citing evidence;
* cites a record that was never in the residual's evidence or candidates;
* proposes an action outside the permitted vocabulary;
* attaches a journal batch that does not balance, names an unknown account, or
  whose total does not equal the exact unexplained amount;
* claims RESOLVE on a case whose amounts do not actually agree to the paisa.

A rejected proposal is downgraded to UNRESOLVED and the reasons are recorded.
Nothing is silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision
from app.services.accounting.journal import (
    PERMITTED_ACTIONS,
    JournalBatch,
    verify_journal_batch,
)
from app.services.ai.interfaces import ResidualCase

RULE_VERIFY_EVIDENCE = "RULE-VER-001"
RULE_VERIFY_ACTION = "RULE-VER-002"
RULE_VERIFY_JOURNAL = "RULE-VER-003"
RULE_VERIFY_AMOUNT = "RULE-VER-004"
RULE_VERIFY_CANDIDATE = "RULE-VER-005"


@dataclass(slots=True)
class VerificationOutcome:
    accepted: bool
    result: ArbitrationResult
    reasons: List[str] = field(default_factory=list)
    journal_verdict: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reasons": self.reasons,
            "journal_verdict": self.journal_verdict,
            "result": self.result.to_dict(),
        }


def verify_arbitration(
    residual: ResidualCase,
    result: ArbitrationResult,
    batch: Optional[JournalBatch] = None,
) -> VerificationOutcome:
    """Verify one proposal against the residual it claims to explain."""
    reasons: List[str] = []
    permitted = set(residual.permitted_records())

    # --- provenance -------------------------------------------------------
    unknown_evidence = [e for e in result.evidence if e not in permitted]
    if unknown_evidence:
        reasons.append(
            f"cites records outside the residual evidence: {unknown_evidence} "
            f"({RULE_VERIFY_EVIDENCE})"
        )

    if result.decision is ArbitrationDecision.RESOLVE and not result.evidence:
        reasons.append(
            f"decision RESOLVE requires at least one referenced source record "
            f"({RULE_VERIFY_EVIDENCE})"
        )

    # --- action vocabulary ------------------------------------------------
    if result.proposed_action and result.proposed_action not in PERMITTED_ACTIONS:
        reasons.append(
            f"proposed action {result.proposed_action!r} is not in the permitted "
            f"vocabulary {list(PERMITTED_ACTIONS)} ({RULE_VERIFY_ACTION})"
        )

    # --- a RESOLVE must actually reconcile --------------------------------
    if result.decision is ArbitrationDecision.RESOLVE:
        matched_candidate = next(
            (c for c in residual.candidates if c.candidate_id in set(result.evidence)),
            None,
        )
        if matched_candidate is not None and not matched_candidate.amount_matches_exactly:
            reasons.append(
                f"RESOLVE pairs this residual with {matched_candidate.candidate_id}, "
                f"whose amount differs by "
                f"{matched_candidate.amount_delta_paisa} paise "
                f"({RULE_VERIFY_AMOUNT})"
            )

    # --- journal batch ----------------------------------------------------
    journal_verdict: Optional[Dict[str, Any]] = None
    if batch is not None:
        verdict = verify_journal_batch(batch, permitted_source_records=permitted)
        journal_verdict = verdict.to_dict()
        if not verdict.accepted:
            reasons.extend(f"{r} ({RULE_VERIFY_JOURNAL})" for r in verdict.reasons)

    if not reasons:
        return VerificationOutcome(
            accepted=True, result=result, reasons=[], journal_verdict=journal_verdict
        )

    # --- rejected: downgrade rather than discard --------------------------
    downgraded = ArbitrationResult(
        residual_id=result.residual_id,
        decision=ArbitrationDecision.UNRESOLVED,
        confidence=0.0,
        reason=(
            "Proposal rejected by deterministic verification and downgraded to "
            "UNRESOLVED. " + "; ".join(reasons)
        ),
        evidence=[e for e in result.evidence if e in permitted],
        proposed_action=None,
        journal_entry=None,
        requires_human_review=True,
        arbitrator=result.arbitrator,
    )
    return VerificationOutcome(
        accepted=False,
        result=downgraded,
        reasons=reasons,
        journal_verdict=journal_verdict,
    )
