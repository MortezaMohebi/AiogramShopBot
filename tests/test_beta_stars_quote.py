"""P3 customer-visible invoice amounts agree with Telegram Stars policy."""

from types import SimpleNamespace

import pytest

from channels.contracts import Platform
from services.shop_cart import CartQuote, QuoteLine, CartRejected, telegram_stars_total


def quote(*, types=("digital",), stars=(9,), discount=0, shipping=0):
    """Build a minimal nonpersistent quote for currency-policy assertions."""
    lines = tuple(
        QuoteLine(
            product=SimpleNamespace(product_type=kind, price_stars=price),
            quantity=2, line_total=500,
        ) for kind, price in zip(types, stars, strict=True)
    )
    return CartQuote(
        lines=lines, subtotal=1000, discount=discount,
        shipping=shipping, total=1000 - discount + shipping,
        shipping_required=False, shipping_label=None,
        coupon_code=None,
    )


def test_telegram_digital_cart_uses_xtr_not_fake_irr_total():
    """Digital items in Telegram display Stars before confirmation."""
    assert telegram_stars_total(Platform.TELEGRAM, quote()) == 18


def test_physical_and_bale_orders_keep_native_irr():
    """Payment currency derives from platform and product kind."""
    assert telegram_stars_total(
        Platform.TELEGRAM, quote(types=("physical",), stars=(None,)),
    ) is None
    assert telegram_stars_total(Platform.BALE, quote()) is None


def test_mixed_telegram_goods_fail_explicitly():
    """A mixed Telegram cart is not invoiced as fiat or Stars."""
    with pytest.raises(CartRejected):
        telegram_stars_total(
            Platform.TELEGRAM,
            quote(types=("digital", "physical"), stars=(9, None)),
        )


def test_telegram_digital_disallows_irr_coupon_or_missing_star_price():
    """Do not silently convert coupon discounts into Telegram Stars."""
    with pytest.raises(CartRejected):
        telegram_stars_total(
            Platform.TELEGRAM, quote(stars=(None,)),
        )
    with pytest.raises(CartRejected):
        telegram_stars_total(
            Platform.TELEGRAM, quote(discount=100),
        )
