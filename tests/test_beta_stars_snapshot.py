"""Telegram Stars Order snapshot prevents unapproved provider price changes."""

from types import SimpleNamespace

import pytest

from services.shop_payments import PaymentRejected, frozen_stars_amount


def test_exact_snapshotted_stars_price_is_used_instead_of_live_product_price():
    """Changing Product.price_stars after checkout cannot change the Invoice."""
    line = SimpleNamespace(
        quantity=2, unit_price_stars_snapshot=9,
    )
    product = SimpleNamespace(price_stars=50, product_type="digital")
    assert frozen_stars_amount([(line, product)], expected_total=18) == 18


def test_missing_or_mismatched_star_snapshot_blocks_invoice():
    """No fall-through to live price, fiat or ambiguous merchant credit."""
    product = SimpleNamespace(price_stars=9, product_type="digital")
    for quantity, price, total in (
        (2, None, 18),
        (2, 9, 19),
        (0, 9, 0),
        (1, -5, -5),
    ):
        line = SimpleNamespace(
            quantity=quantity, unit_price_stars_snapshot=price,
        )
        with pytest.raises(PaymentRejected):
            frozen_stars_amount([(line, product)], expected_total=total)
