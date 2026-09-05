"""Rule proposal by pattern induction.

When an acquirer changes its narration format, the same failure appears many
times in one run: a payout is proved but its credit cannot be located, and a
credit sits unidentified for exactly the same amount. Arbitration pairs those
two sides, and a pairing tells us something the base engine did not know - which
settlement key is hiding inside a narration it could not parse.

This module turns a set of those pairings into a proposed extraction rule. The
induction is deterministic and evidence-driven, not generative:

1. Locate the target settlement key as a substring of the normalized narration.
2. Take the whitespace token containing it, and split it into the literal text
   before the key, the key, and the literal text after.
3. Take the preceding token as an anchor, so the pattern cannot fire on an
   arbitrary number elsewhere on the statement.
4. Group samples by that shape. A shape needs MIN_SUPPORT independent examples
   before it is proposed at all - one coincidence is not a format.
5. Build the pattern, then verify it against every supporting sample AND
   against a control set of narrations it must not claim.

A proposal that fails step 5 is discarded rather than surfaced. The point of
proposing a rule is to save an operator work, and a rule they have to debug is
worse than no rule.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.normalization.text import normalize_text
from app.services.rules.dynamic import (
    MIN_KEY_LENGTH,
    ReferenceExtractionRule,
    RuleType,
    validate_reference_rule,
)

#: How many independent examples a narration shape needs before it is proposed.
MIN_SUPPORT = 3

RULE_INDUCTION = "RULE-PROP-001"


@dataclass(slots=True)
class ReferenceSample:
    """One narration whose true settlement key arbitration established."""

    residual_id: str
    narration: str
    target_key: str
    bank_transaction_id: Optional[str] = None

    @property
    def normalized(self) -> str:
        return normalize_text(self.narration)


@dataclass(slots=True)
class RuleProposal:
    """A candidate rule, with the evidence that produced it."""

    name: str
    rule_type: str
    pattern: str
    marker: str
    description: str
    support: int
    supporting_residuals: List[str] = field(default_factory=list)
    sample_narrations: List[str] = field(default_factory=list)
    expression: str = ""
    induction_rule: str = RULE_INDUCTION

    def parameters(self) -> Dict[str, Any]:
        if self.rule_type == RuleType.AMOUNT_TOLERANCE:
            tol = 1
            if "tolerance_paisa=" in self.pattern:
                try:
                    tol = int(self.pattern.split("tolerance_paisa=")[-1])
                except ValueError:
                    pass
            return {
                "gateway": self.marker or "*",
                "tolerance_paisa": tol,
                "description": self.description,
            }
        elif self.rule_type == RuleType.DATE_TOLERANCE:
            return {
                "max_days": 3,
                "description": self.description,
            }
        return {
            "pattern": self.pattern,
            "marker": self.marker,
            "key_group": 1,
            "description": self.description,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "rule_type": self.rule_type,
            "pattern": self.pattern,
            "marker": self.marker,
            "description": self.description,
            "support": self.support,
            "supporting_residuals": self.supporting_residuals,
            "sample_narrations": self.sample_narrations,
            "expression": self.expression,
            "induction_rule": self.induction_rule,
        }


@dataclass(slots=True)
class _Shape:
    anchor: str
    prefix: str
    suffix: str
    key_length: int


def _shape_of(sample: ReferenceSample) -> Optional[_Shape]:
    """Derive the narration shape around the known settlement key."""
    text = sample.normalized
    key = sample.target_key
    if not key or len(key) < MIN_KEY_LENGTH:
        return None

    tokens = text.split(" ")
    for position, token in enumerate(tokens):
        offset = token.find(key)
        if offset == -1:
            continue
        prefix = token[:offset]
        suffix = token[offset + len(key) :]
        # The anchor is the previous alphabetic token. Without one the pattern
        # would be unanchored, which validate_reference_rule rejects anyway.
        anchor = ""
        for earlier in reversed(tokens[:position]):
            if earlier and any(ch.isalpha() for ch in earlier):
                anchor = earlier
                break
        if not anchor:
            return None
        return _Shape(
            anchor=anchor, prefix=prefix, suffix=suffix, key_length=len(key)
        )
    return None


def _build_pattern(shape: _Shape) -> str:
    parts = [re.escape(shape.anchor), r"\s+"]
    if shape.prefix:
        parts.append(re.escape(shape.prefix))
    parts.append(rf"(\d{{{shape.key_length}}})")
    if shape.suffix:
        parts.append(re.escape(shape.suffix))
    return "".join(parts)


def propose_reference_rules(
    samples: Sequence[ReferenceSample],
    controls: Optional[Sequence[str]] = None,
    min_support: int = MIN_SUPPORT,
) -> List[RuleProposal]:
    """Induce extraction rules from paired narrations.

    ``controls`` are narrations the rule must NOT claim: ordinary statement
    lines from the same run. Checking against them is what stops a pattern that
    happens to fit the samples from also swallowing unrelated credits.
    """
    grouped: Dict[Tuple[str, str, str, int], List[ReferenceSample]] = defaultdict(list)
    for sample in samples:
        shape = _shape_of(sample)
        if shape is None:
            continue
        grouped[(shape.anchor, shape.prefix, shape.suffix, shape.key_length)].append(
            sample
        )

    proposals: List[RuleProposal] = []
    for (anchor, prefix, suffix, key_length), members in sorted(
        grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])
    ):
        if len(members) < min_support:
            continue

        shape = _Shape(anchor=anchor, prefix=prefix, suffix=suffix, key_length=key_length)
        pattern = _build_pattern(shape)
        params = {"pattern": pattern, "marker": anchor, "key_group": 1}
        if validate_reference_rule(params):
            continue

        rule = ReferenceExtractionRule(
            rule_id="PROPOSAL",
            name=f"{anchor} narration format",
            pattern=pattern,
            marker=anchor,
        )

        # Must recover the correct key for every supporting sample.
        if any(rule.extract(s.normalized) != s.target_key for s in members):
            continue

        # Must not claim a narration it was not induced from.
        if controls and any(rule.extract(normalize_text(c)) for c in controls):
            continue

        proposals.append(
            RuleProposal(
                name=f"Recover settlement key from {anchor} narrations",
                rule_type=RuleType.REFERENCE_EXTRACTION,
                pattern=pattern,
                marker=anchor,
                description=(
                    f"Narrations anchored on {anchor!r} carry the settlement key "
                    f"as {key_length} digits"
                    + (f" behind the literal prefix {prefix!r}" if prefix else "")
                    + (f" and before {suffix!r}" if suffix else "")
                    + f". Induced from {len(members)} independent arbitration "
                    f"pairings in this run ({RULE_INDUCTION})."
                ),
                support=len(members),
                supporting_residuals=sorted(s.residual_id for s in members),
                sample_narrations=[s.narration for s in members[:3]],
                expression=f"extract {anchor} narration key: {pattern}",
            )
        )

    return proposals


def propose_amount_tolerance_rules(
    samples: Sequence[Dict[str, Any]],
    min_support: int = 1,
) -> List[RuleProposal]:
    """Induce rounding tolerance rules from paired residual anomalies.

    ``samples`` carry dictionaries with keys: ``residual_id``, ``gateway``, ``variance_paisa``, ``narration``.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        gateway = str(sample.get("gateway") or "XYZ")
        var_paisa = abs(int(sample.get("variance_paisa", 0)))
        if 0 < var_paisa <= 100:
            grouped[gateway].append(sample)

    proposals: List[RuleProposal] = []
    for gateway, members in grouped.items():
        if len(members) < min_support:
            continue
        max_tol = max(abs(int(m.get("variance_paisa", 1))) for m in members)
        proposals.append(
            RuleProposal(
                name=f"Allow {gateway} gateway rounding tolerance (+-{max_tol} paisa)",
                rule_type=RuleType.AMOUNT_TOLERANCE,
                pattern=f"tolerance_paisa={max_tol}",
                marker=gateway,
                description=(
                    f"Gateway {gateway!r} produces recurring minor rounding "
                    f"variances up to {max_tol} paisa. Induced from {len(members)} "
                    f"arbitration resolution(s)."
                ),
                support=len(members),
                supporting_residuals=sorted(m["residual_id"] for m in members if "residual_id" in m),
                sample_narrations=[m.get("narration", "") for m in members[:3] if m.get("narration")],
                expression=f"allow rounding variance <= {max_tol} paisa for {gateway}",
            )
        )
    return proposals
