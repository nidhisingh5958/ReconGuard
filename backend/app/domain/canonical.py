"""Canonical normalized transaction model.

Normalization NEVER destroys the source value. Every normalized field that had
to be transformed is paired with its original in ``normalization_trace`` so the
audit trail can show exactly what the engine did and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from app.domain.enums import SourceSystem, TransactionType


@dataclass(slots=True)
class NormalizationStep:
    """One field-level transformation, fully reversible for audit purposes."""

    field_name: str
    original_value: str
    normalized_value: str
    rule: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field_name,
            "original_value": self.original_value,
            "normalized_value": self.normalized_value,
            "rule": self.rule,
        }


@dataclass(slots=True)
class CanonicalTransaction:
    canonical_id: str
    source: SourceSystem
    source_record_id: str
    transaction_type: TransactionType
    amount_paisa: int
    date: Optional[date]
    reference: str
    counterparty: str
    invoice_id: Optional[str] = None
    payment_id: Optional[str] = None
    settlement_id: Optional[str] = None
    order_id: Optional[str] = None
    currency: str = "INR"
    metadata: Dict[str, Any] = field(default_factory=dict)
    normalization_trace: List[NormalizationStep] = field(default_factory=list)

    def trace_dicts(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self.normalization_trace]
