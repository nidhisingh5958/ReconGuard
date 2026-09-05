"""Monetary arithmetic for ReconGuard.

RULE: money is ALWAYS an ``int`` number of paise. Floating point is never used
for money anywhere in this system. Rates are expressed in basis points (bps)
so that a rate is itself an exact integer: 1 bps = 0.01%, so 2% = 200 bps.

Rounding is banker-free: Indian financial convention here is ROUND_HALF_UP on
the paisa, applied once per derived component (not compounded), which is what
payment gateways do when they publish a fee breakdown.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Union

Paisa = int

BPS_DENOMINATOR = Decimal(10_000)
_HUNDRED = Decimal(100)


def rupees_to_paisa(value: Union[str, int, Decimal]) -> Paisa:
    """Convert a rupee value to integer paise.

    Accepts strings ("1000.25"), ints (whole rupees) or Decimals. Never floats:
    passing a float is a programming error and raises, because 1000.25 is not
    exactly representable in binary floating point.
    """
    if isinstance(value, float):  # pragma: no cover - defensive
        raise TypeError("float is not an accepted money input; pass str/Decimal/int")
    dec = Decimal(value) if not isinstance(value, Decimal) else value
    return int((dec * _HUNDRED).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def paisa_to_rupees(value: Paisa) -> Decimal:
    """Exact rupee Decimal for a paise amount (for display / export only)."""
    return (Decimal(int(value)) / _HUNDRED).quantize(Decimal("0.01"))


def apply_rate_bps(amount_paisa: Paisa, rate_bps: int) -> Paisa:
    """Apply a basis-point rate to a paise amount, ROUND_HALF_UP to the paisa.

    ``apply_rate_bps(100_000_00, 200)`` -> 2% of Rs.100,000.00 = 200000 paise.
    """
    if rate_bps == 0:
        return 0
    product = Decimal(int(amount_paisa)) * Decimal(int(rate_bps)) / BPS_DENOMINATOR
    return int(product.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_inr(amount_paisa: Paisa) -> str:
    """Format paise as an Indian-grouped rupee string: 9762000 -> 'Rs.97,620.00'."""
    negative = amount_paisa < 0
    whole, frac = divmod(abs(int(amount_paisa)), 100)
    digits = str(whole)
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        grouped = ",".join(groups + [tail])
    else:
        grouped = digits
    return f"{'-' if negative else ''}Rs.{grouped}.{frac:02d}"


def sum_paisa(*values: Paisa) -> Paisa:
    """Explicit integer summation helper (keeps call sites obviously exact)."""
    total = 0
    for v in values:
        total += int(v)
    return total
