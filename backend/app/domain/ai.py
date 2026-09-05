"""Interfaces for the FUTURE AI layer.

Nothing in the deterministic pipeline imports an implementation from here. The
arbitrator only ever receives residual cases, never the whole dataset, and it
cannot write a financial record directly: it returns a proposal that the
deterministic verifier must accept before anything is booked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from app.domain.enums import ArbitrationDecision, JournalEntryStatus


@dataclass(slots=True)
class JournalEntry:
    """Double-entry proposal. Rejected unless debits equal credits exactly."""

    journal_id: str
    date: date
    debit_account: str
    credit_account: str
    amount_paisa: int
    description: str
    source_records: List[str] = field(default_factory=list)
    confidence: float = 0.0
    status: JournalEntryStatus = JournalEntryStatus.DRAFT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "journal_id": self.journal_id,
            "date": self.date.isoformat(),
            "debit_account": self.debit_account,
            "credit_account": self.credit_account,
            "amount_paisa": self.amount_paisa,
            "description": self.description,
            "source_records": self.source_records,
            "confidence": self.confidence,
            "status": self.status.value,
        }


@dataclass(slots=True)
class ArbitrationResult:
    residual_id: str
    decision: ArbitrationDecision
    confidence: float
    reason: str
    evidence: List[str] = field(default_factory=list)
    proposed_action: Optional[str] = None
    journal_entry: Optional[JournalEntry] = None
    requires_human_review: bool = True
    arbitrator: str = "none"
    model_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "residual_id": self.residual_id,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "proposed_action": self.proposed_action,
            "journal_entry": self.journal_entry.to_dict() if self.journal_entry else None,
            "requires_human_review": self.requires_human_review,
            "arbitrator": self.arbitrator,
            "model_metadata": self.model_metadata,
        }
