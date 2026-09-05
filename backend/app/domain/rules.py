"""Rule model. Infrastructure only, automatic promotion is NOT implemented."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.domain.enums import RuleStatus, RuleType


@dataclass(slots=True)
class Rule:
    rule_id: str
    name: str
    description: str
    rule_type: RuleType
    expression: str
    version: int = 1
    status: RuleStatus = RuleStatus.ACTIVE
    created_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parameters: Dict[str, Any] = field(default_factory=dict)
    occurrence_count: int = 0
    backtest_result: Dict[str, Any] = field(default_factory=dict)
    expected_match_gain: int = 0
    expected_false_positive_rate: float = 0.0
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "rule_type": self.rule_type.value,
            "expression": self.expression,
            "version": self.version,
            "status": self.status.value,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "validation_count": self.validation_count,
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "parameters": self.parameters,
            "occurrence_count": self.occurrence_count,
            "backtest_result": self.backtest_result,
            "expected_match_gain": self.expected_match_gain,
            "expected_false_positive_rate": self.expected_false_positive_rate,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }
