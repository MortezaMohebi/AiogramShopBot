"""Unit acceptance for legal Telegram mixed checkout split planning."""

from dataclasses import dataclass

import pytest

from services.shop_mixed_checkout import (
    MixedCheckoutError, build_split_plan, checkout_quote_fingerprint,
)


@dataclass(frozen=True)
class Line:
    """An immutable, independent cart-line fixture."""

    product_id: int
    product_type: str
    quantity: int
    unit_price_irr: int
    unit_price_stars: int | None
    requires_shipping: bool


LINES = (
    Line(1, "physical", 2, 100_000, None, True),
    Line(2, "digital", 3, 50_000, 9, False),
)


def test_two_independent_payment_currencies_and_fiat_discount():
    """Only the physical half receives IRR shipping and coupon discounts."""
    plan = build_split_plan(
        LINES, shipping_irr=25_000, physical_discount_irr=20_000,
        coupon_code="SAVE", shipping_label="Post",
    )
    assert plan.physical.total_irr == 205_000
    assert plan.physical.currency == "IRR"
    assert plan.digital.total_stars == 27
    assert plan.digital.discount_irr == 0
    assert plan.digital.currency == "XTR"


def test_quote_fingerprint_changes_on_customer_visible_price_update():
    """The approval token changes after a digital Stars price change."""
    old = checkout_quote_fingerprint(
        LINES, shipping_irr=25_000, physical_discount_irr=20_000,
        policy_token="test",
    )
    changed = LINES[:1] + (Line(2, "digital", 3, 50_000, 10, False),)
    new = checkout_quote_fingerprint(
        changed, shipping_irr=25_000, physical_discount_irr=20_000,
        policy_token="test",
    )
    assert len(old) == 12 and old != new


def test_checkout_proof_changes_on_new_delivery_address():
    """Changing an address requires fresh customer approval."""
    old = checkout_quote_fingerprint(
        LINES, shipping_irr=0, physical_discount_irr=0,
        policy_token="test", shipping_address="اول",
    )
    new = checkout_quote_fingerprint(
        LINES, shipping_irr=0, physical_discount_irr=0,
        policy_token="test", shipping_address="دوم",
    )
    assert old != new


def test_coupon_cannot_discount_digital_stars():
    """An IRR coupon cannot exceed the physical subtotal."""
    with pytest.raises(MixedCheckoutError):
        build_split_plan(
            LINES, shipping_irr=0, physical_discount_irr=200_000,
        )


def test_invalid_line_does_not_yield_a_partial_checkout():
    """No zero-quantity line may generate a paid Order."""
    broken = (Line(1, "physical", 0, 100_000, None, True), LINES[1])
    with pytest.raises(MixedCheckoutError):
        build_split_plan(
            broken, shipping_irr=0, physical_discount_irr=0,
        )
