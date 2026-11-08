"""Exact Iranian rial amounts and optional toman presentation.

The persisted shop amount and Bale's LabeledPrice.amount are always integers
in IRR. Tomans are *display-only* and must never reach the Bale Bot API.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation


MAX_RIALS = 10**16 - 1


def to_rials(value: int | Decimal | str) -> int:
    """Convert an exact integral amount to a bounded number of rials.

    Do not accept floats or booleans, which could hide rounding mistakes.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Money must be provided as Decimal, int or text.")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid rial amount.") from None
    if not amount.is_finite() or amount < 0 or amount != amount.to_integral_value():
        raise ValueError("Rial amount must be a non-negative integer.")
    if amount > MAX_RIALS:
        raise ValueError("Rial amount exceeds the supported range.")
    return int(amount)


def format_rials(amount: int | Decimal, display_unit: str = "IRR") -> str:
    """Format IRR or toman text without changing the canonical amount."""
    rials = to_rials(amount)
    unit = display_unit.upper()
    if unit == "IRR":
        return f"{rials:,} ریال"
    if unit == "TOMAN":
        tomans = Decimal(rials) / Decimal(10)
        digits = 0 if tomans == tomans.to_integral_value() else 1
        return f"{tomans:,.{digits}f} تومان"
    raise ValueError("Display unit must be IRR or TOMAN.")
