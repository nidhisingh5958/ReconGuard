"""Immutable audit event. Every engine decision emits at least one."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.enums import AuditAction


@dataclass(slots=True)
class AuditEvent:
    audit_id: str
    timestamp: datetime
    action: AuditAction
    actor: str
    reconciliation_id: Optional[str] = None
    run_id: Optional[str] = None
    source_records: List[str] = field(default_factory=list)
    rule_id: Optional[str] = None
    calculation: str = ""
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    evidence: List[str] = field(default_factory=list)
    detail: Dict[str, Any] = field(default_factory=dict)
    system_version: str = "reconguard/0.1.0"

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "timestamp": self.timestamp.isoformat(),
            "action": self.action.value,
            "actor": self.actor,
            "reconciliation_id": self.reconciliation_id,
            "run_id": self.run_id,
            "source_records": self.source_records,
            "rule_id": self.rule_id,
            "calculation": self.calculation,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "evidence": self.evidence,
            "detail": self.detail,
            "system_version": self.system_version,
        }
