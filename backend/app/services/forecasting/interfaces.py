"""Cash position and forecasting seam (next phase).

What ships now is the honest half: the *committed* cash position, derived
entirely from reconciled records. A settlement that is proved but whose credit
has not been located is money contractually owed and not yet received, and that
is a fact, not a forecast.

What does NOT ship is prediction. :class:`CashForecaster` defines the seam a
future model plugs into. Keeping the two apart matters, because a finance team
must always be able to tell which number is an obligation and which is a guess.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence


@dataclass(slots=True)
class CashPositionLine:
    """One dated, evidence-backed movement in the committed cash position."""

    value_date: Optional[str]
    label: str
    amount_paisa: int
    basis: str
    source_records: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value_date": self.value_date,
            "label": self.label,
            "amount_paisa": self.amount_paisa,
            "basis": self.basis,
            "source_records": self.source_records,
        }


@dataclass(slots=True)
class CashPosition:
    """Committed position. Every figure traces to reconciled records."""

    confirmed_received_paisa: int = 0
    committed_inflow_paisa: int = 0
    at_risk_paisa: int = 0
    unexplained_paisa: int = 0
    lines: List[CashPositionLine] = field(default_factory=list)
    as_of: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "confirmed_received_paisa": self.confirmed_received_paisa,
            "committed_inflow_paisa": self.committed_inflow_paisa,
            "at_risk_paisa": self.at_risk_paisa,
            "unexplained_paisa": self.unexplained_paisa,
            "as_of": self.as_of,
            "lines": [line.to_dict() for line in self.lines],
            "basis": "deterministic",
            "includes_prediction": False,
        }


@dataclass(slots=True)
class ForecastPoint:
    value_date: date
    expected_inflow_paisa: int
    confidence: float
    method: str


class CashForecaster(abc.ABC):
    """Seam for a future predictive layer. Nothing implements this yet."""

    name = "abstract"

    @abc.abstractmethod
    def forecast(
        self, horizon_days: int, history: Sequence[Any]
    ) -> List[ForecastPoint]:
        """Project future inflows. Must label its method and confidence."""


class NoForecaster(CashForecaster):
    """The default: returns nothing rather than an unfounded projection."""

    name = "none"

    def forecast(
        self, horizon_days: int, history: Sequence[Any]
    ) -> List[ForecastPoint]:
        return []
