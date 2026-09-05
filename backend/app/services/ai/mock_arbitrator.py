"""Mock AI provider implementation.

Provides deterministic responses for synthetic anomaly types so the entire AI
arbitration workflow, verification gate, human review queue, and audit trail
can be exercised end-to-end without API costs or network connectivity.

Known synthetic anomaly behavior:
- ROUNDING_ERROR: RESOLVE (small variance explained by rounding)
- INVOICE_TYPO: RESOLVE (reference string distance/typo match explained)
- CUSTOMER_NAME_ALIAS / CUSTOMER_ALIAS: RESOLVE (alias similarity matched)
- UNKNOWN_BANK_CREDIT: UNRESOLVED (unless unique exact candidate exists)
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.core.config import get_settings
from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision
from app.services.accounting.journal import JournalBatch, JournalBuilder
from app.services.ai.confidence import compute_evidence_confidence
from app.services.ai.deterministic_arbitrator import DeterministicArbitrator, _as_date
from app.services.ai.interfaces import ResidualArbitrator, ResidualCase


class MockResidualArbitrator(ResidualArbitrator):
    """Mock LLM Provider that simulates structured AI decisions based on evidence."""

    name = "mock"
    uses_model = False

    def __init__(self, fallback: Optional[ResidualArbitrator] = None) -> None:
        self.fallback = fallback or DeterministicArbitrator()
        self._journal = JournalBuilder()

    def resolve(self, residual: ResidualCase) -> ArbitrationResult:
        result, _ = self.resolve_with_journal(residual)
        return result

    def resolve_with_journal(
        self, residual: ResidualCase
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        settings = get_settings()
        reason_codes = set(residual.reason_codes)

        # Check candidate match
        candidate = residual.candidates[0] if residual.candidates else None
        
        # 1. CUSTOMER_ALIAS or CUSTOMER_NAME_ALIAS anomaly
        if "CUSTOMER_NAME_ALIAS" in reason_codes or "CUSTOMER_ALIAS" in reason_codes or "COUNTERPARTY_ALIAS_RESOLVED" in reason_codes:
            counterparty_candidate = candidate.counterparty if candidate else "ACME TECH PVT"
            eval_result = compute_evidence_confidence(
                amount_delta_paisa=candidate.amount_delta_paisa if candidate else 0,
                date_delta_days=candidate.date_delta_days if candidate else 1,
                counterparty1=residual.counterparty or "Acme Technologies Pvt Ltd",
                counterparty2=counterparty_candidate,
                model_confidence=0.96,
            )
            
            amount = residual.exposure_paisa or abs(residual.variance_paisa) or (candidate.amount_paisa if candidate else 100000)
            evidence = list(set(residual.source_records + ([candidate.candidate_id] if candidate else [])))
            
            action = "ACCRUE_SETTLEMENT_RECEIVABLE"
            batch = self._journal.build(
                residual_id=residual.residual_id,
                action=action,
                amount_paisa=amount,
                source_records=evidence,
                confidence=eval_result.final_confidence,
                value_date=_as_date(residual.value_date),
            )
            
            decision = (
                ArbitrationDecision.RESOLVE
                if eval_result.final_confidence >= settings.auto_resolve_threshold
                else ArbitrationDecision.PROBABLE
            )

            result = ArbitrationResult(
                residual_id=residual.residual_id,
                decision=decision,
                confidence=eval_result.final_confidence,
                reason=(
                    f"Customer entity alias confirmed with {int(eval_result.counterparty_score * 100)}% similarity. "
                    f"Order counterparty '{residual.counterparty}' matches Bank entity '{counterparty_candidate}'."
                ),
                evidence=evidence,
                proposed_action=action,
                journal_entry=batch.entries[0] if batch and batch.entries else None,
                requires_human_review=(decision != ArbitrationDecision.RESOLVE),
                arbitrator=self.name,
                model_metadata={
                    "provider": "mock",
                    "model": "mock-sonnet-v1",
                    "anomaly_category": "CUSTOMER_ALIAS",
                    "model_confidence": eval_result.model_confidence,
                    "evidence_score": eval_result.evidence_score,
                    "final_confidence": eval_result.final_confidence,
                    "breakdown": eval_result.to_dict(),
                },
            )
            return result, batch

        # 2. INVOICE_TYPO anomaly
        if "INVOICE_TYPO" in reason_codes or "INVOICE_TYPO_RESOLVED" in reason_codes or "UNRECOGNISED_REFERENCE_FORMAT" in reason_codes:
            ref1 = "INV-10B29"
            ref2 = "INV-10829"
            eval_result = compute_evidence_confidence(
                amount_delta_paisa=0,
                date_delta_days=1,
                counterparty1=residual.counterparty,
                counterparty2=candidate.counterparty if candidate else residual.counterparty,
                reference1=ref1,
                reference2=ref2,
                model_confidence=0.97,
            )

            amount = residual.exposure_paisa or abs(residual.variance_paisa) or 50000
            evidence = list(set(residual.source_records + ([candidate.candidate_id] if candidate else ["INV-10829"])))
            
            action = "ACCRUE_SETTLEMENT_RECEIVABLE"
            batch = self._journal.build(
                residual_id=residual.residual_id,
                action=action,
                amount_paisa=amount,
                source_records=evidence,
                confidence=eval_result.final_confidence,
                value_date=_as_date(residual.value_date),
            )

            decision = (
                ArbitrationDecision.RESOLVE
                if eval_result.final_confidence >= settings.auto_resolve_threshold
                else ArbitrationDecision.PROBABLE
            )

            result = ArbitrationResult(
                residual_id=residual.residual_id,
                decision=decision,
                confidence=eval_result.final_confidence,
                reason=(
                    f"Single-character reference typo identified ({ref1} -> {ref2}) with exact amount match ({amount} paise)."
                ),
                evidence=evidence,
                proposed_action=action,
                journal_entry=batch.entries[0] if batch and batch.entries else None,
                requires_human_review=(decision != ArbitrationDecision.RESOLVE),
                arbitrator=self.name,
                model_metadata={
                    "provider": "mock",
                    "model": "mock-sonnet-v1",
                    "anomaly_category": "INVOICE_TYPO",
                    "model_confidence": eval_result.model_confidence,
                    "evidence_score": eval_result.evidence_score,
                    "final_confidence": eval_result.final_confidence,
                    "breakdown": eval_result.to_dict(),
                },
            )
            return result, batch

        # 3. ROUNDING_ERROR anomaly
        if "ROUNDING_ERROR" in reason_codes or "ROUNDING_TOLERANCE_APPLIED" in reason_codes:
            eval_result = compute_evidence_confidence(
                amount_delta_paisa=100,  # Rs.1.00
                date_delta_days=0,
                counterparty1=residual.counterparty,
                counterparty2=residual.counterparty,
                model_confidence=0.98,
            )

            amount = residual.exposure_paisa or abs(residual.variance_paisa) or 100
            evidence = list(set(residual.source_records))
            
            action = "BOOK_VARIANCE"
            batch = self._journal.build(
                residual_id=residual.residual_id,
                action=action,
                amount_paisa=amount,
                source_records=evidence,
                confidence=eval_result.final_confidence,
                value_date=_as_date(residual.value_date),
            )

            result = ArbitrationResult(
                residual_id=residual.residual_id,
                decision=ArbitrationDecision.RESOLVE,
                confidence=eval_result.final_confidence,
                reason="Immaterial rounding variance of 100 paise (Rs 1.00) attributed to fee calculation precision.",
                evidence=evidence,
                proposed_action=action,
                journal_entry=batch.entries[0] if batch and batch.entries else None,
                requires_human_review=False,
                arbitrator=self.name,
                model_metadata={
                    "provider": "mock",
                    "model": "mock-sonnet-v1",
                    "anomaly_category": "ROUNDING_ERROR",
                    "model_confidence": eval_result.model_confidence,
                    "evidence_score": eval_result.evidence_score,
                    "final_confidence": eval_result.final_confidence,
                    "breakdown": eval_result.to_dict(),
                },
            )
            return result, batch

        # 4. UNKNOWN_BANK_CREDIT anomaly with no exact candidate -> UNRESOLVED
        if "UNKNOWN_BANK_CREDIT" in reason_codes and (not candidate or not candidate.amount_matches_exactly):
            evidence = list(set(residual.source_records))
            result = ArbitrationResult(
                residual_id=residual.residual_id,
                decision=ArbitrationDecision.UNRESOLVED,
                confidence=0.18,
                reason=(
                    "Bank credit has no reliable corresponding order, settlement, or invoice. "
                    "ReconGuard cannot establish a supported match. ACTION: Human investigation required."
                ),
                evidence=evidence,
                proposed_action=None,
                journal_entry=None,
                requires_human_review=True,
                arbitrator=self.name,
                model_metadata={
                    "provider": "mock",
                    "model": "mock-sonnet-v1",
                    "anomaly_category": "UNKNOWN_BANK_CREDIT",
                    "model_confidence": 0.18,
                    "evidence_score": 0.18,
                    "final_confidence": 0.18,
                },
            )
            return result, None

        # Fallback to deterministic arbitrator policy for any other residual type
        return self.fallback.resolve_with_journal(residual)
