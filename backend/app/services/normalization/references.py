"""Bank reference extraction.

Bank narrations are the messiest data in the pipeline. The same settlement can
arrive as any of:

    RAZORPAY SETTLEMENT SET-10291
    RAZORPAY SETTLE 10291
    RZP SET-10291
    Settlement payout / 10291
    NEFT-RZPSET10291-CITI
    RZP SET-1029                 (truncated by the bank field width)

The approach is deliberately NOT fuzzy string similarity. We extract structured
candidate keys from the narration and look them up in an exact index. A match
is therefore either provable or absent, and when a truncation forces a prefix
lookup we require the prefix to resolve to exactly one settlement before we
will use it, and we label the result so a human can see the weaker basis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.services.normalization.text import normalize_text

RULE_REFERENCE_EXTRACT = "RULE-NORM-020"
RULE_REFERENCE_PREFIX = "RULE-NORM-021"

#: Markers that identify a narration as a payment-gateway settlement payout.
#: Strong markers are unambiguous enough to be matched inside a compacted token
#: such as NEFT-RZPSET10291-CITI. Weak markers must stand as their own word,
#: because 'SET' as a substring would also fire on ASSET, OFFSET and RESET.
STRONG_GATEWAY_MARKERS = ("RAZORPAY", "RZPY", "RZP", "SETTLEMENT", "SETTLE", "PAYOUT")
WEAK_GATEWAY_MARKERS = ("SET", "STL")
GATEWAY_MARKERS = STRONG_GATEWAY_MARKERS + WEAK_GATEWAY_MARKERS

_DIGIT_RUN = re.compile(r"\d{4,}")
_ALNUM_TOKEN = re.compile(r"[A-Z]+\d+|\d+[A-Z]+")


@dataclass(slots=True)
class ExtractedReference:
    """Structured candidates pulled out of a single bank narration."""

    original: str
    normalized: str
    numeric_keys: List[str] = field(default_factory=list)
    token_keys: List[str] = field(default_factory=list)
    looks_like_gateway_payout: bool = False

    def to_dict(self) -> dict:
        return {
            "original": self.original,
            "normalized": self.normalized,
            "numeric_keys": self.numeric_keys,
            "token_keys": self.token_keys,
            "looks_like_gateway_payout": self.looks_like_gateway_payout,
        }


def settlement_numeric_key(settlement_id: Optional[str]) -> str:
    """The digit core of a settlement id: 'SET-10291' -> '10291'."""
    if not settlement_id:
        return ""
    digits = re.sub(r"[^0-9]", "", settlement_id)
    return digits


def extract_reference(description: str, reference: str = "") -> ExtractedReference:
    """Pull every plausible identifier key out of a narration plus ref field."""
    combined = f"{description or ''} {reference or ''}"
    normalized = normalize_text(combined)

    numeric_keys: List[str] = []
    for match in _DIGIT_RUN.findall(normalized):
        if match not in numeric_keys:
            numeric_keys.append(match)

    token_keys: List[str] = []
    for token in normalized.split(" "):
        if not token:
            continue
        if _ALNUM_TOKEN.fullmatch(token) and token not in token_keys:
            token_keys.append(token)
    # A compacted narration such as RZPSET10291 hides its digits inside one
    # token; pull those out too so the numeric index can still find them.
    for token in token_keys:
        digits = re.sub(r"[^0-9]", "", token)
        if len(digits) >= 4 and digits not in numeric_keys:
            numeric_keys.append(digits)

    words = normalized.split(" ")
    looks_like_payout = any(
        marker in word for word in words for marker in STRONG_GATEWAY_MARKERS
    ) or any(word in WEAK_GATEWAY_MARKERS for word in words)

    return ExtractedReference(
        original=combined.strip(),
        normalized=normalized,
        numeric_keys=numeric_keys,
        token_keys=token_keys,
        looks_like_gateway_payout=looks_like_payout,
    )
