"""Rule validation by replay.

A rule is promoted because a replay showed it helped, never because something
was confident about it. Validation runs the engine twice over the same dataset,
once without the candidate rule and once with it, and compares the results
record by record.

The comparison is only meaningful because the engine is reproducible: identical
input yields identical output including ids, so every difference between the two
runs is attributable to the rule and to nothing else.

Two measurements matter, and the second matters more:

* **improvement** - how many records moved into MATCHED;
* **regression** - whether ANY record that was MATCHED stopped being matched.

A rule that fixes six records and breaks one is not a good trade. Regressions
are therefore disqualifying rather than merely subtracted, and the specific
records are named so a human can see what would have broken.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import AccountingConfig, ReconciliationConfig
from app.domain.enums import ReconciliationStatus
from app.domain.sources import SourceDataset
from app.services.reconciliation.engine import ReconciliationEngine
from app.services.rules.dynamic import (
    AmountToleranceRule,
    DateToleranceRule,
    DynamicRuleSet,
    ReferenceExtractionRule,
    RuleType,
    validate_dynamic_rule_params,
)

VERDICT_IMPROVES = "IMPROVES"
VERDICT_NEUTRAL = "NEUTRAL"
VERDICT_REGRESSES = "REGRESSES"
VERDICT_INVALID = "INVALID"


@dataclass(slots=True)
class ValidationReport:
    """The measured effect of one candidate rule."""

    validation_id: str
    rule_id: str
    dataset_id: str
    baseline_matches: int = 0
    candidate_matches: int = 0
    match_delta: int = 0
    baseline_residuals: int = 0
    candidate_residuals: int = 0
    residual_delta: int = 0
    baseline_match_rate: float = 0.0
    candidate_match_rate: float = 0.0
    regressions: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    verdict: str = VERDICT_NEUTRAL
    detail: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def match_rate_delta_pct(self) -> float:
        return round((self.candidate_match_rate - self.baseline_match_rate) * 100, 4)

    @property
    def approved(self) -> bool:
        return self.verdict == VERDICT_IMPROVES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "rule_id": self.rule_id,
            "dataset_id": self.dataset_id,
            "baseline_matches": self.baseline_matches,
            "candidate_matches": self.candidate_matches,
            "match_delta": self.match_delta,
            "baseline_residuals": self.baseline_residuals,
            "candidate_residuals": self.candidate_residuals,
            "residual_delta": self.residual_delta,
            "baseline_match_rate": round(self.baseline_match_rate, 6),
            "candidate_match_rate": round(self.candidate_match_rate, 6),
            "match_rate_delta_pct": self.match_rate_delta_pct,
            "regressions": self.regressions,
            "improvements": self.improvements,
            "verdict": self.verdict,
            "approved": self.approved,
            "detail": self.detail,
            "created_at": self.created_at.isoformat(),
        }


def validate_rule(
    dataset: SourceDataset,
    rule_id: str,
    parameters: Dict[str, Any],
    validation_id: str = "VAL-00001",
    rule_type: str = RuleType.REFERENCE_EXTRACTION,
    accounting: Optional[AccountingConfig] = None,
    reconciliation: Optional[ReconciliationConfig] = None,
    active_rules: Optional[Sequence[Any]] = None,
) -> ValidationReport:
    """Replay ``dataset`` with and without the candidate rule and compare."""
    report = ValidationReport(
        validation_id=validation_id,
        rule_id=rule_id,
        dataset_id=dataset.dataset_id,
    )

    structural = validate_dynamic_rule_params(rule_type, parameters)
    if structural:
        report.verdict = VERDICT_INVALID
        report.detail = {"structural_errors": structural}
        return report

    existing_ref = [r for r in (active_rules or []) if isinstance(r, ReferenceExtractionRule)]
    existing_amt = [r for r in (active_rules or []) if isinstance(r, AmountToleranceRule)]
    existing_date = [r for r in (active_rules or []) if isinstance(r, DateToleranceRule)]

    baseline_set = DynamicRuleSet(
        reference_rules=existing_ref,
        amount_tolerance_rules=existing_amt,
        date_tolerance_rules=existing_date,
    )

    cand_ref = list(existing_ref)
    cand_amt = list(existing_amt)
    cand_date = list(existing_date)

    rule_name = str(parameters.get("name", rule_id))
    if rule_type == RuleType.REFERENCE_EXTRACTION:
        cand_ref.append(ReferenceExtractionRule.from_parameters(rule_id, rule_name, parameters))
    elif rule_type == RuleType.AMOUNT_TOLERANCE:
        cand_amt.append(AmountToleranceRule.from_parameters(rule_id, rule_name, parameters))
    elif rule_type == RuleType.DATE_TOLERANCE:
        cand_date.append(DateToleranceRule.from_parameters(rule_id, rule_name, parameters))

    candidate_set = DynamicRuleSet(
        reference_rules=cand_ref,
        amount_tolerance_rules=cand_amt,
        date_tolerance_rules=cand_date,
    )

    baseline = ReconciliationEngine(
        accounting=accounting, reconciliation=reconciliation, rules=baseline_set
    ).run(dataset, run_id="VALIDATE-BASE")
    candidate = ReconciliationEngine(
        accounting=accounting, reconciliation=reconciliation, rules=candidate_set
    ).run(dataset, run_id="VALIDATE-CAND")

    before = {r.reconciliation_id: r.status for r in baseline.results}
    after = {r.reconciliation_id: r.status for r in candidate.results}

    for reconciliation_id, previous in before.items():
        now = after.get(reconciliation_id)
        if now is None:
            continue
        was_matched = previous is ReconciliationStatus.MATCHED
        is_matched = now is ReconciliationStatus.MATCHED
        if was_matched and not is_matched:
            report.regressions.append(
                f"{reconciliation_id}: {previous.value} -> {now.value}"
            )
        elif is_matched and not was_matched:
            report.improvements.append(
                f"{reconciliation_id}: {previous.value} -> {now.value}"
            )

    report.baseline_matches = baseline.metrics.deterministic_matches
    report.candidate_matches = candidate.metrics.deterministic_matches
    report.match_delta = report.candidate_matches - report.baseline_matches
    report.baseline_residuals = baseline.metrics.residuals
    report.candidate_residuals = candidate.metrics.residuals
    report.residual_delta = report.candidate_residuals - report.baseline_residuals
    report.baseline_match_rate = baseline.metrics.match_rate
    report.candidate_match_rate = candidate.metrics.match_rate

    if report.regressions:
        report.verdict = VERDICT_REGRESSES
    elif report.match_delta > 0:
        report.verdict = VERDICT_IMPROVES
    else:
        report.verdict = VERDICT_NEUTRAL

    imp_count = len(report.improvements)
    reg_count = len(report.regressions)
    total_changes = imp_count + reg_count
    precision = (imp_count / total_changes) if total_changes > 0 else 1.0

    report.detail = {
        "records_processed": candidate.metrics.records_processed,
        "records_affected": total_changes,
        "additional_matches": max(0, report.match_delta),
        "false_positives": reg_count,
        "false_negatives": report.candidate_residuals,
        "precision": round(precision, 4),
        "estimated_ai_calls_avoided": max(0, report.match_delta),
        "estimated_cost_avoided_usd": round(max(0, report.match_delta) * 0.002, 4),
        "baseline_unexplained_paisa": baseline.metrics.unexplained_value_paisa,
        "candidate_unexplained_paisa": candidate.metrics.unexplained_value_paisa,
        "unexplained_delta_paisa": (
            candidate.metrics.unexplained_value_paisa
            - baseline.metrics.unexplained_value_paisa
        ),
        "rule_pattern": parameters.get("pattern"),
        "rule_marker": parameters.get("marker"),
        "active_rules_at_validation": [r.rule_id for r in (active_rules or [])],
    }
    return report
