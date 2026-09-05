"""Evaluation harness for the Residual AI Arbitrator.

Evaluates AI arbitration proposals against the synthetic dataset's hidden
ground-truth anomaly labels (AnomalyType enum).

Calculates:
- Precision
- Recall
- F1 score
- False-positive rate
- False-negative rate
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AnomalyType, ArbitrationDecision
from app.models.entities import ArbitrationRow, ReconciliationRecord


@dataclass(slots=True)
class EvaluationMetrics:
    run_id: str
    arbitrator: str
    total_residuals: int
    ai_resolutions: int
    correct_resolutions: int
    incorrect_resolutions: int
    false_positives: int
    false_negatives: int
    true_positives: int
    true_negatives: int
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float
    false_negative_rate: float
    breakdown_by_anomaly: Dict[str, Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "arbitrator": self.arbitrator,
            "total_residuals": self.total_residuals,
            "ai_resolutions": self.ai_resolutions,
            "correct_resolutions": self.correct_resolutions,
            "incorrect_resolutions": self.incorrect_resolutions,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "breakdown_by_anomaly": self.breakdown_by_anomaly,
        }


def evaluate_run_arbitration(session: Session, run_id: str) -> EvaluationMetrics:
    """Evaluate AI arbitration decisions against hidden ground truth."""
    arb_rows = list(
        session.scalars(
            select(ArbitrationRow).where(ArbitrationRow.run_id == run_id)
        ).all()
    )
    if not arb_rows:
        return EvaluationMetrics(
            run_id=run_id,
            arbitrator="none",
            total_residuals=0,
            ai_resolutions=0,
            correct_resolutions=0,
            incorrect_resolutions=0,
            false_positives=0,
            false_negatives=0,
            true_positives=0,
            true_negatives=0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            false_positive_rate=0.0,
            false_negative_rate=0.0,
            breakdown_by_anomaly={},
        )

    # Get corresponding ground-truth records
    record_ids = [r.residual_id for r in arb_rows]
    records = list(
        session.scalars(
            select(ReconciliationRecord).where(
                ReconciliationRecord.reconciliation_id.in_(record_ids)
            )
        ).all()
    )
    by_id = {rec.reconciliation_id: rec for rec in records}

    arbitrator_name = arb_rows[0].arbitrator if arb_rows else "unknown"
    tp = fp = fn = tn = 0
    correct_resolutions = 0
    incorrect_resolutions = 0

    resolvable_anomalies = {
        AnomalyType.INVOICE_TYPO.value,
        AnomalyType.CUSTOMER_NAME_ALIAS.value,
        AnomalyType.ROUNDING_ERROR.value,
        AnomalyType.DATE_FORMAT_DIFFERENCE.value,
        AnomalyType.TRUNCATED_BANK_REFERENCE.value,
    }

    breakdown: Dict[str, Dict[str, Any]] = {}

    for arb in arb_rows:
        rec = by_id.get(arb.residual_id)
        # Ground truth anomaly label if present in detail/metadata
        anomaly = None
        if rec and rec.evidence:
            for ev in rec.evidence:
                if isinstance(ev, dict) and ev.get("detail"):
                    anomaly = ev["detail"].get("anomaly_type")
                    if anomaly:
                        break

        if not anomaly and arb.model_metadata:
            anomaly = arb.model_metadata.get("anomaly_category")

        anomaly_key = anomaly or "UNKNOWN"
        if anomaly_key not in breakdown:
            breakdown[anomaly_key] = {"total": 0, "resolved": 0, "correct": 0}
        breakdown[anomaly_key]["total"] += 1

        is_resolvable = anomaly_key in resolvable_anomalies or (
            arb.confidence >= 0.85 and arb.verification_accepted
        )

        ai_resolved = arb.decision in (ArbitrationDecision.RESOLVE.value, ArbitrationDecision.PROBABLE.value)
        if ai_resolved:
            breakdown[anomaly_key]["resolved"] += 1

        if is_resolvable and ai_resolved:
            tp += 1
            correct_resolutions += 1
            breakdown[anomaly_key]["correct"] += 1
        elif not is_resolvable and ai_resolved:
            fp += 1
            incorrect_resolutions += 1
        elif is_resolvable and not ai_resolved:
            fn += 1
        else:
            tn += 1

    total_ai_resolutions = tp + fp
    precision = (tp / total_ai_resolutions) if total_ai_resolutions > 0 else 1.0
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fpr = (fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    fnr = (fn / (fn + tp)) if (fn + tp) > 0 else 0.0

    return EvaluationMetrics(
        run_id=run_id,
        arbitrator=arbitrator_name,
        total_residuals=len(arb_rows),
        ai_resolutions=total_ai_resolutions,
        correct_resolutions=correct_resolutions,
        incorrect_resolutions=incorrect_resolutions,
        false_positives=fp,
        false_negatives=fn,
        true_positives=tp,
        true_negatives=tn,
        precision=precision,
        recall=recall,
        f1_score=f1,
        false_positive_rate=fpr,
        false_negative_rate=fnr,
        breakdown_by_anomaly=breakdown,
    )
