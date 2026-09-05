"""Deterministic confidence validation layer.

Combines deterministic evidence scores with model assessment to produce an
explainable final confidence score.

The formula:
    final_confidence = 0.80 * evidence_score + 0.20 * min(model_confidence, 0.90)

Where evidence_score is a weighted combination of:
- identifier_score: 1.0 for exact ID/GSTIN match, 0.85 for single-char typo, 0.0 otherwise.
- amount_score: 1.0 for 0 paisa variance, 0.8 for rounding <= 100 paisa, 0.0 otherwise.
- date_score: 1.0 for 0-1 days delta, decaying over date window.
- counterparty_score: token similarity ratio (0.0 to 1.0) for alias matching.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ConfidenceEvaluation:
    model_confidence: float
    evidence_score: float
    final_confidence: float
    identifier_score: float
    amount_score: float
    date_score: float
    counterparty_score: float
    breakdown: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_confidence": round(self.model_confidence, 4),
            "evidence_score": round(self.evidence_score, 4),
            "final_confidence": round(self.final_confidence, 4),
            "identifier_score": round(self.identifier_score, 4),
            "amount_score": round(self.amount_score, 4),
            "date_score": round(self.date_score, 4),
            "counterparty_score": round(self.counterparty_score, 4),
            "breakdown": self.breakdown,
        }


def compute_string_similarity(s1: Optional[str], s2: Optional[str]) -> float:
    """Token / string similarity for counterparty name alias matching."""
    if not s1 or not s2:
        return 0.0
    c1 = re.sub(r"[^\w\s]", "", s1.upper()).strip()
    c2 = re.sub(r"[^\w\s]", "", s2.upper()).strip()
    if c1 == c2:
        return 1.0

    tokens1 = set(c1.split())
    tokens2 = set(c2.split())
    if tokens1 and tokens2:
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        jaccard = len(intersection) / len(union) if union else 0.0
    else:
        jaccard = 0.0

    seq_match = difflib.SequenceMatcher(None, c1, c2).ratio()
    return max(jaccard, seq_match)


def compute_identifier_score(reference1: Optional[str], reference2: Optional[str]) -> float:
    """Score reference / invoice similarity, supporting typo detection."""
    if not reference1 or not reference2:
        return 0.0
    r1 = reference1.strip().upper()
    r2 = reference2.strip().upper()
    if r1 == r2:
        return 1.0

    matcher = difflib.SequenceMatcher(None, r1, r2)
    ratio = matcher.ratio()

    # Single character substitution/typo (e.g. INV-10829 vs INV-10B29)
    if len(r1) == len(r2) and sum(1 for a, b in zip(r1, r2) if a != b) == 1:
        return 0.85

    if ratio >= 0.8:
        return round(ratio, 2)
    return 0.0


def compute_evidence_confidence(
    amount_delta_paisa: int,
    date_delta_days: Optional[int],
    counterparty1: Optional[str],
    counterparty2: Optional[str],
    reference1: Optional[str] = None,
    reference2: Optional[str] = None,
    gstin1: Optional[str] = None,
    gstin2: Optional[str] = None,
    model_confidence: float = 0.5,
) -> ConfidenceEvaluation:
    """Compute evidence score and final combined confidence score."""
    # 1. Identifier Score
    if gstin1 and gstin2 and gstin1.strip().upper() == gstin2.strip().upper():
        id_score = 1.0
    else:
        id_score = compute_identifier_score(reference1, reference2)

    # 2. Amount Score
    abs_amt = abs(amount_delta_paisa)
    if abs_amt == 0:
        amt_score = 1.0
    elif abs_amt <= 100:  # rounding tolerance <= Rs.1
        amt_score = 0.8
    elif abs_amt <= 500:  # <= Rs.5
        amt_score = 0.5
    else:
        amt_score = 0.0

    # 3. Date Score
    if date_delta_days is None:
        dt_score = 0.5
    else:
        abs_days = abs(date_delta_days)
        if abs_days <= 1:
            dt_score = 1.0
        elif abs_days <= 3:
            dt_score = 0.8
        elif abs_days <= 7:
            dt_score = 0.5
        else:
            dt_score = 0.0

    # 4. Counterparty Score
    cp_score = compute_string_similarity(counterparty1, counterparty2)

    # Clamped model confidence (max 0.90)
    clamped_model_conf = max(0.0, min(0.90, model_confidence))

    # Evidence score = weighted combination of deterministic signals
    if id_score > 0:
        w_id, w_amt, w_dt, w_cp = 0.35, 0.30, 0.20, 0.15
    else:
        w_id, w_amt, w_dt, w_cp = 0.00, 0.50, 0.30, 0.20

    evidence_score = (w_id * id_score) + (w_amt * amt_score) + (w_dt * dt_score) + (w_cp * cp_score)

    final_confidence = max(0.0, min(1.0, (0.80 * evidence_score) + (0.20 * clamped_model_conf)))

    breakdown = {
        "formula": "final_confidence = 0.80 * evidence_score + 0.20 * min(model_confidence, 0.90)",
        "weights": {"id": w_id, "amount": w_amt, "date": w_dt, "counterparty": w_cp},
        "signals": {
            "amount_delta_paisa": amount_delta_paisa,
            "date_delta_days": date_delta_days,
            "counterparty_similarity": round(cp_score, 2),
            "identifier_similarity": round(id_score, 2),
        },
    }

    return ConfidenceEvaluation(
        model_confidence=clamped_model_conf,
        evidence_score=evidence_score,
        final_confidence=final_confidence,
        identifier_score=id_score,
        amount_score=amt_score,
        date_score=dt_score,
        counterparty_score=cp_score,
        breakdown=breakdown,
    )
