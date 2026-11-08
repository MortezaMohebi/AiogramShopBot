"""Pure monetary tests without connecting to any payment service."""

from decimal import Decimal

import pytest

from services.shop_money import format_rials, to_rials


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (1000, 1000),
        ("1000", 1000),
        (Decimal("1000.00"), 1000),
        (0, 0),
    ],
)
def test_exact_rial_amount(amount, expected):
    """Preserve whole rials without binary float conversion."""
    assert to_rials(amount) == expected


@pytest.mark.parametrize("amount", [False, 1.2, "-1", "12.3", "NaN", "Infinity"])
def test_rial_amount_rejects_invalid_values(amount):
    """Reject booleans, floats, fractions, negatives and nonfinite values."""
    with pytest.raises(ValueError):
        to_rials(amount)


def test_toman_display_never_changes_wallet_payment_amount():
    """Convert only the text shown to people, never the canonical rials."""
    assert format_rials(12345, "IRR") == "12,345 ریال"
    assert format_rials(12345, "TOMAN") == "1,234.5 تومان"
    assert to_rials(Decimal("12345")) == 12345
