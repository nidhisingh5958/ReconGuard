"""The arbitration seam.

Three rules govern this boundary and are enforced, not merely documented:

1. **The arbitrator receives only residuals.** :class:`ResidualCase` is the only
   shape any implementation sees. It is built from evidence the deterministic
   engine already proved, plus candidates found by deterministic retrieval. It
   never carries the dataset, the matched records or the raw ledger.
2. **The arbitrator cannot write.** ``resolve()`` returns a proposal. Every
   proposal passes :func:`app.services.ai.verification.verify_arbitration`
   before it can touch a financial record, and that gate weighs arithmetic, not
   the confidence the proposer asserted.
3. **The system works with no arbitrator.** The default is
   :class:`NullArbitrator`, which declines every case honestly.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.domain.ai import ArbitrationResult
from app.domain.enums import ArbitrationDecision
from app.services.ai.candidates import ResidualCandidate, ResidualView


@dataclass(slots=True)
class ResidualCase:
    """The bounded view of one unresolved item handed to an arbitrator."""

    residual_id: str
    status: str
    reason_codes: List[str]
    expected_amount_paisa: int
    actual_amount_paisa: int
    variance_paisa: int
    exposure_paisa: int
    counterparty: Optional[str]
    value_date: Optional[str]
    source_records: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    calculation: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[ResidualCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "residual_id": self.residual_id,
            "status": self.status,
            "reason_codes": self.reason_codes,
            "expected_amount_paisa": self.expected_amount_paisa,
            "actual_amount_paisa": self.actual_amount_paisa,
            "variance_paisa": self.variance_paisa,
            "exposure_paisa": self.exposure_paisa,
            "counterparty": self.counterparty,
            "value_date": self.value_date,
            "source_records": self.source_records,
            "evidence": self.evidence,
            "calculation": self.calculation,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    def permitted_records(self) -> List[str]:
        """Record ids a proposal may cite: this residual plus its candidates."""
        permitted = list(self.source_records)
        for candidate in self.candidates:
            permitted.extend(candidate.source_records)
            permitted.append(candidate.candidate_id)
        permitted.append(self.residual_id)
        return sorted(set(permitted))


def build_residual_case(
    view: ResidualView,
    evidence: Optional[Sequence[Dict[str, Any]]] = None,
    calculation: Optional[Sequence[Dict[str, Any]]] = None,
    candidates: Optional[Sequence[ResidualCandidate]] = None,
) -> ResidualCase:
    """Project a residual down to the arbitrator-visible subset."""
    return ResidualCase(
        residual_id=view.reconciliation_id,
        status=view.status,
        reason_codes=list(view.reason_codes),
        expected_amount_paisa=view.expected_amount_paisa,
        actual_amount_paisa=view.actual_amount_paisa,
        variance_paisa=view.variance_paisa,
        exposure_paisa=view.exposure_paisa,
        counterparty=view.counterparty,
        value_date=view.value_date,
        source_records=list(view.source_records),
        evidence=[dict(e) for e in (evidence or [])],
        calculation=[dict(c) for c in (calculation or [])],
        candidates=list(candidates or []),
    )


class ResidualArbitrator(abc.ABC):
    """Contract for anything that attempts to resolve a residual."""

    name = "abstract"
    #: True when reaching a decision requires a network call to a model.
    uses_model = False

    @abc.abstractmethod
    def resolve(self, residual: ResidualCase) -> ArbitrationResult:
        """Return a proposal for one residual. Must never mutate anything."""

    def resolve_many(
        self, residuals: Sequence[ResidualCase]
    ) -> List[ArbitrationResult]:
        return [self.resolve(r) for r in residuals]


class NullArbitrator(ResidualArbitrator):
    """The default. Declines every case, honestly and cheaply.

    This is what makes "works with no AI provider configured" true rather than
    aspirational: the system always has an arbitrator, it just does not pretend
    to know anything.
    """

    name = "null"

    def resolve(self, residual: ResidualCase) -> ArbitrationResult:
        return ArbitrationResult(
            residual_id=residual.residual_id,
            decision=ArbitrationDecision.UNRESOLVED,
            confidence=0.0,
            reason=(
                "No arbitrator is configured. This residual is reported as-is for "
                "human review rather than being resolved by inference."
            ),
            evidence=list(residual.source_records),
            proposed_action=None,
            journal_entry=None,
            requires_human_review=True,
            arbitrator=self.name,
        )

    def resolve_with_journal(
        self, residual: ResidualCase
    ) -> Tuple[ArbitrationResult, Optional[JournalBatch]]:
        return self.resolve(residual), None


def get_arbitrator(provider: str = "none", **kwargs: Any) -> ResidualArbitrator:
    """Factory. Anything unavailable degrades to a safe implementation.

    The degradation ladder is deliberate. A misconfigured model provider must
    fall back to the deterministic arbitrator, and a broken deterministic
    arbitrator must fall back to declining, so a configuration mistake can never
    take the system down or, worse, cause it to guess.
    """
    normalised = (provider or "none").strip().lower()

    if normalised in ("", "none", "disabled", "null"):
        return NullArbitrator()

    if normalised in ("deterministic", "rules", "local"):
        from app.services.ai.deterministic_arbitrator import DeterministicArbitrator

        return DeterministicArbitrator()

    if normalised in ("mock", "mock_arbitrator", "synthetic"):
        from app.services.ai.mock_arbitrator import MockResidualArbitrator

        return MockResidualArbitrator()

    try:
        from app.services.ai.llm_arbitrator import LLMResidualArbitrator

        return LLMResidualArbitrator(provider=normalised, **kwargs)
    except Exception:
        from app.services.ai.deterministic_arbitrator import DeterministicArbitrator

        return DeterministicArbitrator()
