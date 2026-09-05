"""Text normalization primitives.

Normalization is lossy by nature, so every helper here is paired with a caller
that records the original value alongside the normalized one. We never write a
normalized value back over a source record.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional

RULE_TEXT_NORMALIZE = "RULE-NORM-001"
RULE_COUNTERPARTY_ALIAS = "RULE-NORM-002"
RULE_INVOICE_NORMALIZE = "RULE-NORM-003"

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^A-Z0-9 ]+")
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

#: Legal-form and courtesy suffixes that carry no identifying information.
_COMPANY_STOPWORDS = frozenset(
    {
        "PVT",
        "PRIVATE",
        "LTD",
        "LIMITED",
        "LLP",
        "INC",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "AND",
        "THE",
    }
)


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def normalize_text(value: Optional[str]) -> str:
    """Uppercase, strip accents, drop punctuation, collapse whitespace."""
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    upper = ascii_only.upper()
    depunctuated = _PUNCTUATION.sub(" ", upper)
    return normalize_whitespace(depunctuated)


def normalize_identifier(value: Optional[str]) -> str:
    """Collapse an identifier to comparable form: 'set-10291' -> 'SET10291'."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", value.upper())


def counterparty_key(name: Optional[str]) -> str:
    """Alias-resistant key for a counterparty name.

    'Acme Retail Pvt Ltd', 'ACME RETAIL' and 'Acme  Retail.' all collapse to
    'ACME RETAIL', which is what lets an aliased customer name still match
    without any fuzzy string scoring.
    """
    normalized = normalize_text(name)
    if not normalized:
        return ""
    tokens = [t for t in normalized.split(" ") if t and t not in _COMPANY_STOPWORDS]
    return " ".join(tokens) if tokens else normalized


def invoice_key(invoice_id: Optional[str]) -> str:
    """Comparable invoice key. 'INV-1O001' keeps its typo; see numeric_invoice_key."""
    return normalize_identifier(invoice_id)


def numeric_invoice_key(invoice_id: Optional[str]) -> str:
    """Digits only, with common OCR-style confusions folded.

    Typos in an invoice register are overwhelmingly O/0, I/1, S/5 and B/8
    substitutions. Folding them is a deterministic, reversible rule, not a
    similarity heuristic, so a resolved typo can be shown as evidence.
    """
    if not invoice_id:
        return ""
    compact = normalize_identifier(invoice_id)
    # Drop the document-type prefix ('INV') so its letters are not folded into
    # digits and mistaken for part of the serial.
    core = re.sub(r"^[A-Z]+", "", compact)
    folded = (
        core.replace("O", "0")
        .replace("I", "1")
        .replace("L", "1")
        .replace("S", "5")
        .replace("B", "8")
    )
    return re.sub(r"[^0-9]", "", folded)


def text_normalization_trace(field_name: str, original: Optional[str]) -> Dict[str, str]:
    return {
        "field": field_name,
        "original_value": original or "",
        "normalized_value": normalize_text(original),
        "rule": RULE_TEXT_NORMALIZE,
    }
