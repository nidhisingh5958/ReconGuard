"""Date normalization.

Source systems disagree about date formats. The bank writes 05/09/2026, the
gateway writes 2026-09-05, the invoice register writes 05-Sep-2026. All three
mean the same day and must reconcile without a human deciding that.

Parsing is strictly ordered and explicit. We never guess between an ambiguous
DD/MM and MM/DD by looking at the value: the format list is fixed and the
Indian DD/MM convention wins, which is recorded as a rule so the choice is
auditable rather than accidental.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Tuple

RULE_DATE_NORMALIZE = "RULE-NORM-010"

#: Ordered. First format that parses wins. DD/MM precedes MM/DD deliberately.
DATE_FORMATS: Tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%b %d, %Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def parse_date(value) -> Optional[date]:
    """Parse a date from any supported source format. Returns None if unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_date_with_format(value) -> Tuple[Optional[date], Optional[str]]:
    """Parse and also report which format matched, for the audit trail."""
    if value is None or value == "":
        return None, None
    if isinstance(value, datetime):
        return value.date(), "datetime"
    if isinstance(value, date):
        return value, "date"
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date(), fmt
        except ValueError:
            continue
    return None, None


def days_between(left: Optional[date], right: Optional[date]) -> Optional[int]:
    """Signed day delta ``left - right``. None if either side is unknown."""
    if left is None or right is None:
        return None
    return (left - right).days


def within_tolerance(
    actual: Optional[date], expected: Optional[date], tolerance_days: int
) -> bool:
    delta = days_between(actual, expected)
    if delta is None:
        return False
    return abs(delta) <= tolerance_days


def iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value else None
