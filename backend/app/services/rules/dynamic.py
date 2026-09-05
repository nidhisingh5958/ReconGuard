"""Dynamic rules: rules the engine loads at run time rather than at import time.

This is what makes rule promotion mean something. A promoted rule is not a row
in a table that a dashboard counts; it is executable configuration that changes
what the next reconciliation run matches.

One rule type is implemented, and it is the one that actually recurs in
production: **bank reference extraction**. Acquirers and banks change their
narration format without notice. When they do, the built-in digit-run extractor
stops finding the settlement key, previously-matched payouts fall out to
exceptions, and somebody has to teach the system the new shape.

A `REFERENCE_EXTRACTION` rule is a named regex with a capture group that yields
a settlement key. It is deliberately not arbitrary code:

* the pattern must compile;
* it must declare exactly one capturing group;
* it must be anchored to a marker so it cannot match every number on a statement;
* it is applied only when the built-in extractor found nothing usable.

Those constraints are checked at proposal time and again at promotion time, so a
malformed or dangerously broad rule never reaches an ACTIVE state.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

MAX_PATTERN_LENGTH = 240
MIN_KEY_LENGTH = 4


class RuleType:
    REFERENCE_EXTRACTION = "REFERENCE_EXTRACTION"
    AMOUNT_TOLERANCE = "AMOUNT_TOLERANCE"
    DATE_TOLERANCE = "DATE_TOLERANCE"


@dataclass(slots=True)
class RuleValidationError(Exception):
    """Raised when a dynamic rule is structurally unsafe or unusable."""

    reasons: List[str] = field(default_factory=list)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "; ".join(self.reasons)


@dataclass(slots=True)
class ReferenceExtractionRule:
    """Extract a settlement key from a bank narration the built-ins missed."""

    rule_id: str
    name: str
    pattern: str
    #: A literal token that must be present before the pattern is even tried.
    marker: str
    description: str = ""
    key_group: int = 1

    _compiled: Optional[re.Pattern] = None

    def compile(self) -> re.Pattern:
        if self._compiled is None:
            self._compiled = re.compile(self.pattern)
        return self._compiled

    def extract(self, normalized_narration: str) -> Optional[str]:
        """Return the settlement key this rule finds, or None."""
        if self.marker and self.marker.upper() not in normalized_narration.upper():
            return None
        match = self.compile().search(normalized_narration)
        if not match:
            return None
        try:
            key = match.group(self.key_group)
        except (IndexError, re.error):
            return None
        if not key:
            return None
        digits = re.sub(r"[^0-9]", "", key)
        return digits if len(digits) >= MIN_KEY_LENGTH else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "pattern": self.pattern,
            "marker": self.marker,
            "key_group": self.key_group,
            "description": self.description,
        }

    @classmethod
    def from_parameters(cls, rule_id: str, name: str, params: Dict[str, Any]):
        return cls(
            rule_id=rule_id,
            name=name,
            pattern=str(params.get("pattern", "")),
            marker=str(params.get("marker", "")),
            key_group=int(params.get("key_group", 1)),
            description=str(params.get("description", "")),
        )


@dataclass(slots=True)
class AmountToleranceRule:
    """Allow a small rounding discrepancy (e.g. +-1 paisa) for a gateway."""

    rule_id: str
    name: str
    gateway: str
    tolerance_paisa: int = 1
    description: str = ""

    def matches_gateway(self, gateway_name: Optional[str]) -> bool:
        if not self.gateway or self.gateway == "*":
            return True
        if not gateway_name:
            return True
        return self.gateway.upper() in gateway_name.upper()

    def allows_variance(self, variance_paisa: int) -> bool:
        return abs(variance_paisa) <= self.tolerance_paisa

    @classmethod
    def from_parameters(cls, rule_id: str, name: str, params: Dict[str, Any]):
        return cls(
            rule_id=rule_id,
            name=name,
            gateway=str(params.get("gateway", "*")),
            tolerance_paisa=int(params.get("tolerance_paisa", 1)),
            description=str(params.get("description", "")),
        )


@dataclass(slots=True)
class DateToleranceRule:
    """Allow an extended date window for settlement credit matching."""

    rule_id: str
    name: str
    max_days: int = 3
    description: str = ""

    def allows_date_delta(self, delta_days: int) -> bool:
        return abs(delta_days) <= self.max_days

    @classmethod
    def from_parameters(cls, rule_id: str, name: str, params: Dict[str, Any]):
        return cls(
            rule_id=rule_id,
            name=name,
            max_days=int(params.get("max_days", 3)),
            description=str(params.get("description", "")),
        )


def validate_reference_rule(params: Dict[str, Any]) -> List[str]:
    """Structural safety checks for reference extraction rules."""
    reasons: List[str] = []
    pattern = str(params.get("pattern", "") or "")
    marker = str(params.get("marker", "") or "")

    if not pattern:
        reasons.append("pattern is required")
    elif len(pattern) > MAX_PATTERN_LENGTH:
        reasons.append(
            f"pattern exceeds {MAX_PATTERN_LENGTH} characters, which is far beyond "
            "anything a narration format needs"
        )
    else:
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            reasons.append(f"pattern does not compile: {exc}")
        else:
            if compiled.groups != 1:
                reasons.append(
                    f"pattern must declare exactly one capturing group, found "
                    f"{compiled.groups}"
                )

    if not marker:
        reasons.append(
            "marker is required: an unanchored pattern would claim every number "
            "on the statement, including amounts and account numbers"
        )
    elif len(marker) < 3:
        reasons.append("marker must be at least 3 characters to be discriminating")

    return reasons


def validate_amount_tolerance_rule(params: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    try:
        tol = int(params.get("tolerance_paisa", 1))
        if tol <= 0 or tol > 100:
            reasons.append("tolerance_paisa must be between 1 and 100 (<= 1 INR)")
    except (ValueError, TypeError):
        reasons.append("tolerance_paisa must be an integer")
    return reasons


def validate_date_tolerance_rule(params: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    try:
        days = int(params.get("max_days", 3))
        if days <= 0 or days > 7:
            reasons.append("max_days must be between 1 and 7 days")
    except (ValueError, TypeError):
        reasons.append("max_days must be an integer")
    return reasons


def validate_dynamic_rule_params(rule_type: str, params: Dict[str, Any]) -> List[str]:
    if rule_type == RuleType.REFERENCE_EXTRACTION:
        return validate_reference_rule(params)
    elif rule_type == RuleType.AMOUNT_TOLERANCE:
        return validate_amount_tolerance_rule(params)
    elif rule_type == RuleType.DATE_TOLERANCE:
        return validate_date_tolerance_rule(params)
    return [f"unsupported rule type: {rule_type}"]


@dataclass
class DynamicRuleSet:
    """The active dynamic rules for one reconciliation run."""

    reference_rules: List[ReferenceExtractionRule] = field(default_factory=list)
    amount_tolerance_rules: List[AmountToleranceRule] = field(default_factory=list)
    date_tolerance_rules: List[DateToleranceRule] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.reference_rules or self.amount_tolerance_rules or self.date_tolerance_rules)

    def extract_keys(self, normalized_narration: str) -> List[tuple]:
        """Return ``(key, rule_id)`` for every dynamic rule that fires."""
        found: List[tuple] = []
        for rule in self.reference_rules:
            key = rule.extract(normalized_narration)
            if key:
                found.append((key, rule.rule_id))
        return found

    def check_amount_tolerance(self, variance_paisa: int, gateway: Optional[str] = None) -> Optional[str]:
        for rule in self.amount_tolerance_rules:
            if rule.matches_gateway(gateway) and rule.allows_variance(variance_paisa):
                return rule.rule_id
        return None

    def check_date_tolerance(self, delta_days: int) -> Optional[str]:
        for rule in self.date_tolerance_rules:
            if rule.allows_date_delta(delta_days):
                return rule.rule_id
        return None

    @property
    def rule_ids(self) -> List[str]:
        ids = [r.rule_id for r in self.reference_rules]
        ids.extend(r.rule_id for r in self.amount_tolerance_rules)
        ids.extend(r.rule_id for r in self.date_tolerance_rules)
        return ids

    @classmethod
    def from_rows(cls, rows: Sequence[Any]) -> "DynamicRuleSet":
        """Build from RuleRow records whose status is ACTIVE."""
        reference_rules: List[ReferenceExtractionRule] = []
        amount_rules: List[AmountToleranceRule] = []
        date_rules: List[DateToleranceRule] = []

        for row in rows:
            params = row.parameters or {}
            if row.rule_type == RuleType.REFERENCE_EXTRACTION:
                if not params.get("pattern") or validate_reference_rule(params):
                    continue
                reference_rules.append(
                    ReferenceExtractionRule.from_parameters(row.rule_id, row.name, params)
                )
            elif row.rule_type == RuleType.AMOUNT_TOLERANCE:
                if validate_amount_tolerance_rule(params):
                    continue
                amount_rules.append(
                    AmountToleranceRule.from_parameters(row.rule_id, row.name, params)
                )
            elif row.rule_type == RuleType.DATE_TOLERANCE:
                if validate_date_tolerance_rule(params):
                    continue
                date_rules.append(
                    DateToleranceRule.from_parameters(row.rule_id, row.name, params)
                )

        return cls(
            reference_rules=reference_rules,
            amount_tolerance_rules=amount_rules,
            date_tolerance_rules=date_rules,
        )
