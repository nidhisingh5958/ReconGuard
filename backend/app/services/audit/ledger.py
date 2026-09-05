"""Append-only audit ledger.

Every decision the engine makes writes an event here before the run completes.
The ledger is append-only by construction: there is no update or delete, and
state changes are recorded as previous_state/new_state pairs rather than by
overwriting anything.

The bar an event has to clear is that it can answer "why was this matched?"
without the reader needing access to the engine source. That means the literal
arithmetic and the source record ids both live on the event.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.core.ids import SequenceIdFactory
from app.core.versioning import SYSTEM_VERSION
from app.domain.audit import AuditEvent
from app.domain.enums import AuditAction

DEFAULT_ACTOR = "deterministic-engine"


class AuditLedger:
    """Collects audit events for a single reconciliation run."""

    def __init__(
        self,
        run_id: Optional[str] = None,
        actor: str = DEFAULT_ACTOR,
        system_version: str = SYSTEM_VERSION,
    ) -> None:
        self.run_id = run_id
        self.actor = actor
        self.system_version = system_version
        self._ids = SequenceIdFactory("AUD", width=6)
        self.events: List[AuditEvent] = []

    def record(
        self,
        action: AuditAction,
        *,
        reconciliation_id: Optional[str] = None,
        source_records: Optional[Iterable[str]] = None,
        rule_id: Optional[str] = None,
        calculation: str = "",
        previous_state: Optional[str] = None,
        new_state: Optional[str] = None,
        evidence: Optional[Iterable[str]] = None,
        detail: Optional[Dict[str, Any]] = None,
        actor: Optional[str] = None,
    ) -> AuditEvent:
        event = AuditEvent(
            audit_id=self._ids.next(),
            timestamp=AuditEvent.now(),
            action=action,
            actor=actor or self.actor,
            reconciliation_id=reconciliation_id,
            run_id=self.run_id,
            source_records=list(source_records or []),
            rule_id=rule_id,
            calculation=calculation,
            previous_state=previous_state,
            new_state=new_state,
            evidence=list(evidence or []),
            detail=dict(detail or {}),
            system_version=self.system_version,
        )
        self.events.append(event)
        return event

    def bind_run(self, run_id: str) -> None:
        """Attach a run id once it is known, including to already-written events."""
        self.run_id = run_id
        for event in self.events:
            if event.run_id is None:
                event.run_id = run_id

    def __len__(self) -> int:
        return len(self.events)

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.events]
