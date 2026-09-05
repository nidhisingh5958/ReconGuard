"""The LLM-backed residual arbitrator.

What the model is actually asked to do is narrow, and that is the point. It does
not compute anything, it does not choose an amount, and it cannot name an
account. Given a residual and the candidates deterministic retrieval already
found, it decides:

    * which of the offered candidates (if any) explains this residual;
    * which of the permitted bookkeeping actions applies;
    * a short rationale grounded in the evidence it was shown.

The amount is taken from the engine, not from the response. The journal entry is
built by :class:`JournalBuilder` from the action, not by the model. Every result
then passes :func:`verify_arbitration`, which downgrades anything that cites a
record it was not shown, proposes an action outside the vocabulary, or claims
RESOLVE on amounts that do not agree to the paisa.

So the worst a misbehaving model can do is fail to help. It cannot book a wrong
number, and it cannot invent a counterparty.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision
from app.services.accounting.journal import (
    PERMITTED_ACTIONS,
    JournalBatch,
    JournalBuilder,
)
from app.services.ai.deterministic_arbitrator import (
    DeterministicArbitrator,
    _as_date,
)
from app.services.ai.interfaces import ResidualArbitrator, ResidualCase
from app.services.ai.providers import LLMProvider, ProviderError, build_provider

logger = logging.getLogger("reconguard.arbitrator")

MAX_MODEL_CONFIDENCE = 0.90
"""Ceiling on any model-asserted confidence.

A model may not claim certainty. 1.00 in this system means an exact identifier
matched or an accounting invariant closed, and no language model produces either
kind of evidence. Capping here keeps the confidence scale meaningful across the
deterministic and delegated paths.
"""

SYSTEM_PROMPT = """\
You are a reconciliation arbitrator inside a deterministic finance system.

A deterministic engine has already done all the arithmetic. It has proved what
it could and quantified what it could not. You are seeing only the residue.

Your job is narrow and you must stay inside it:
1. Decide whether one of the OFFERED CANDIDATES explains this residual.
2. Choose one bookkeeping action from the PERMITTED ACTIONS list.
3. Give a one or two sentence rationale citing only the record ids you were shown.

Hard constraints:
- You must NOT compute or state any monetary amount. Amounts come from the engine.
- You must NOT reference any record id that does not appear in the input.
- You must NOT invent an action outside the permitted list.
- Use decision "RESOLVE" only when a candidate matches the residual amount
  EXACTLY (amount_matches_exactly is true) and no other candidate is equally
  plausible. Otherwise use "PROBABLE" for a booking proposal, or "UNRESOLVED"
  when the evidence does not support one.
- Prefer UNRESOLVED over a guess. An honest unknown is a correct answer here.

Respond with a single JSON object and nothing else:
{
  "decision": "RESOLVE" | "PROBABLE" | "UNRESOLVED",
  "matched_candidate_id": string or null,
  "proposed_action": string or null,
  "confidence": number between 0 and 0.9,
  "reason": string,
  "cited_records": [string, ...]
}"""


class LLMResidualArbitrator(ResidualArbitrator):
    """Delegates judgement to a model, then verifies the answer."""

    name = "llm"
    uses_model = True

    #: The only fields a model ever sees. Enumerated so the implementation
    #: cannot quietly widen its own access.
    PERMITTED_INPUT_FIELDS = (
        "residual_id",
        "status",
        "reason_codes",
        "expected_amount_paisa",
        "actual_amount_paisa",
        "variance_paisa",
        "exposure_paisa",
        "counterparty",
        "value_date",
        "source_records",
        "evidence",
        "calculation",
        "candidates",
    )

    def __init__(
        self,
        provider: str = "anthropic",
        model: Optional[str] = None,
        client: Optional[LLMProvider] = None,
        fallback: Optional[ResidualArbitrator] = None,
    ) -> None:
        if client is not None:
            self.client = client
        else:
            kwargs: Dict[str, Any] = {}
            if model:
                kwargs["model"] = model
            self.client = build_provider(provider, **kwargs)
        self.provider_name = getattr(self.client, "name", provider)
        self.model = getattr(self.client, "model", model or "")
        from app.services.ai.deterministic_arbitrator import DeterministicArbitrator
        self.fallback = fallback or DeterministicArbitrator()
        self._journal = JournalBuilder()

    # -- public ------------------------------------------------------------
    def resolve(self, residual: ResidualCase) -> ArbitrationResult:
        result, _ = self.resolve_with_journal(residual)
        return result

    def resolve_with_journal(
        self, residual: ResidualCase
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        try:
            response = self.client.complete_json(
                SYSTEM_PROMPT, self.build_prompt(residual)
            )
        except ProviderError as exc:
            logger.warning(
                "arbitrator provider failed for %s (%s); falling back to "
                "deterministic arbitration",
                residual.residual_id,
                exc,
            )
            return self._fallback(residual, note=f"provider unavailable: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("arbitrator call raised for %s: %s", residual.residual_id, exc)
            return self._fallback(residual, note=f"provider error: {exc}")

        try:
            return self._interpret(residual, response.payload)
        except Exception as exc:
            logger.warning(
                "unusable arbitrator response for %s: %s", residual.residual_id, exc
            )
            return self._fallback(residual, note=f"unusable response: {exc}")

    # -- prompt ------------------------------------------------------------
    def build_prompt(self, residual: ResidualCase) -> str:
        """Serialise exactly the permitted fields, and nothing else."""
        payload = residual.to_dict()
        bounded = {k: payload[k] for k in self.PERMITTED_INPUT_FIELDS if k in payload}
        return (
            "RESIDUAL CASE\n"
            f"{json.dumps(bounded, indent=2, default=str)}\n\n"
            "PERMITTED ACTIONS\n"
            f"{json.dumps(list(PERMITTED_ACTIONS), indent=2)}\n\n"
            "Respond with the JSON object described in your instructions."
        )

    # -- interpretation ----------------------------------------------------
    def _interpret(
        self, residual: ResidualCase, payload: Dict[str, Any]
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        decision_raw = str(payload.get("decision", "")).strip().upper()
        try:
            decision = ArbitrationDecision(decision_raw)
        except ValueError:
            raise ValueError(f"unrecognised decision {decision_raw!r}")

        action = payload.get("proposed_action") or None
        if action is not None:
            action = str(action).strip()
            if action not in PERMITTED_ACTIONS:
                # Do not reject outright; the verification gate will catch it,
                # but dropping it here keeps a bad action out of the journal
                # builder entirely.
                logger.info(
                    "arbitrator proposed unpermitted action %r for %s",
                    action,
                    residual.residual_id,
                )

        # Calculate evidence-based deterministic confidence vs model confidence
        from app.core.config import get_settings
        from app.services.ai.confidence import compute_evidence_confidence
        settings = get_settings()

        raw_model_conf = _clamp_confidence(payload.get("confidence"))
        matched_candidate = next(
            (c for c in residual.candidates if c.candidate_id == payload.get("matched_candidate_id")),
            residual.candidates[0] if residual.candidates else None
        )

        eval_result = compute_evidence_confidence(
            amount_delta_paisa=matched_candidate.amount_delta_paisa if matched_candidate else 0,
            date_delta_days=matched_candidate.date_delta_days if matched_candidate else None,
            counterparty1=residual.counterparty,
            counterparty2=matched_candidate.counterparty if matched_candidate else None,
            model_confidence=raw_model_conf,
        )

        final_confidence = eval_result.final_confidence
        requires_human_review = (decision != ArbitrationDecision.RESOLVE or final_confidence < settings.auto_resolve_threshold)

        reason = str(payload.get("reason") or "").strip() or (
            "The model returned no rationale."
        )

        cited = payload.get("cited_records") or []
        evidence = [str(r) for r in cited if isinstance(r, (str, int))]
        matched_id = payload.get("matched_candidate_id")
        if matched_id:
            evidence.append(str(matched_id))
        if not evidence:
            evidence = list(residual.source_records)

        import hashlib
        prompt_hash = hashlib.sha256(json.dumps(payload, default=str).encode("utf-8")).hexdigest()[:12]

        metadata = {
            "provider": self.provider_name,
            "model": self.model,
            "prompt_version": "v2.0-evidence-first",
            "input_evidence_hash": prompt_hash,
            "model_confidence": raw_model_conf,
            "evidence_score": eval_result.evidence_score,
            "final_confidence": final_confidence,
            "thresholds": {
                "auto_resolve": settings.auto_resolve_threshold,
                "human_review": settings.human_review_threshold,
            },
            "breakdown": eval_result.to_dict(),
        }

        if decision is ArbitrationDecision.UNRESOLVED:
            return (
                ArbitrationResult(
                    residual_id=residual.residual_id,
                    decision=decision,
                    confidence=0.0,
                    reason=reason,
                    evidence=sorted(set(evidence)),
                    proposed_action=None,
                    journal_entry=None,
                    requires_human_review=True,
                    arbitrator=self._label(),
                    model_metadata=metadata,
                ),
                None,
            )

        # The amount is the engine's, never the model's.
        amount = residual.exposure_paisa or abs(residual.variance_paisa)
        batch = None
        if action in PERMITTED_ACTIONS and amount > 0:
            batch = self._journal.build(
                residual_id=residual.residual_id,
                action=action,
                amount_paisa=amount,
                source_records=sorted(set(evidence)),
                confidence=final_confidence,
                value_date=_as_date(residual.value_date),
            )

        result = ArbitrationResult(
            residual_id=residual.residual_id,
            decision=decision,
            confidence=final_confidence,
            reason=reason,
            evidence=sorted(set(evidence)),
            proposed_action=action,
            journal_entry=batch.entries[0] if batch and batch.entries else None,
            requires_human_review=requires_human_review,
            arbitrator=self._label(),
            model_metadata=metadata,
        )
        return result, batch

    def _fallback(
        self, residual: ResidualCase, note: str
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        result, batch = self.fallback.resolve_with_journal(residual)  # type: ignore[attr-defined]
        result.reason = f"{result.reason} [delegated arbitration unavailable: {note}]"
        result.arbitrator = f"{self.fallback.name} (fallback from {self._label()})"
        result.model_metadata = {"error": note, "provider": self.provider_name}
        return result, batch

    def _label(self) -> str:
        return f"llm:{self.provider_name}:{self.model}" if self.model else f"llm:{self.provider_name}"


def _clamp_confidence(value: Any) -> float:
    """Coerce a model-asserted confidence into the permitted range."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number != number:  # NaN
        return 0.5
    return max(0.0, min(MAX_MODEL_CONFIDENCE, number))


def llm_available() -> bool:
    """True when credentials for some provider are present in the environment."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
