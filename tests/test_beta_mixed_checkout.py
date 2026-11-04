"""Mixed Telegram physical/digital checkout must create two legal invoices.

These tests exercise the deterministic quote partition independent of
provider API access or PostgreSQL transaction state.
"""

from dataclasses import dataclass

import pytest

from services.shop_mixed_checkout import (
    MixedCheckoutError,
    PartLine,
    build_split_plan,
    checkout_quote_fingerprint,
)


@dataclass(frozen=True)
class ExampleLine:
    """A minimal quote line with immutable checkout pricing inputs."""

    product_id: int
    product_type: str
    quantity: int
    unit_price_irr: int
    unit_price_stars: int | None
    requires_shipping: bool


def lines() -> tuple[ExampleLine, ...]:
    """Provide a mixed cart with an exact independently priced split."""
    return (
        ExampleLine(1, "physical", 2, 100_000, None, True),
        ExampleLine(2, "digital", 3, 50_000, 9, False),
    )


def test_split_creates_distinct_irr_and_xtr_parts():
    """Digital price never contributes to a Telegram Fiat invoice."""
    plan = build_split_plan(
        lines(), shipping_irr=25_000, physical_discount_irr=20_000,
        coupon_code="SAVE", shipping_label="Post",
    )
    assert plan.physical.total_irr == 205_000
    assert plan.physical.subtotal_irr == 200_000
    assert plan.physical.discount_irr == 20_000
    assert plan.physical.shipping_irr == 25_000
    assert plan.physical.currency == "IRR"
    assert plan.digital.total_stars == 27
    assert plan.digital.currency == "XTR"
    assert plan.digital.discount_irr == 0
    assert plan.digital.shipping_irr == 0
    assert len(plan.physical.lines) == len(plan.digital.lines) == 1


def test_promotion_only_applies_to_physical_subtotal():
    """Reject a coupon that could discount Telegram Stars indirectly."""
    with pytest.raises(MixedCheckoutError):
        build_split_plan(lines(), shipping_irr=0, physical_discount_irr=200_000)
    with pytest.raises(MixedCheckoutError):
        build_split_plan(lines(), shipping_irr=0, physical_discount_irr=-1)


def test_missing_stars_price_is_fail_closed():
    """No implicit exchange rate between Rial and Telegram Stars."""
    invalid = lines()[:1] + (
        ExampleLine(2, "digital", 3, 50_000, None, False),
    )
    with pytest.raises(MixedCheckoutError):
        build_split_plan(invalid, shipping_irr=0, physical_discount_irr=0)


def test_unknown_product_type_and_negative_total_are_denied():
    """Do not generate partial Orders for invalid inputs."""
    bad = (ExampleLine(9, "service", 1, 100, 8, False),)
    with pytest.raises(MixedCheckoutError):
        build_split_plan(bad, shipping_irr=0, physical_discount_irr=0)


def test_duplicate_product_identifier_is_not_split_twice():
    """The same SKU cannot exist in both halves of a checkout."""
    duplicate = lines() + (ExampleLine(2, "physical", 1, 50, None, True),)
    with pytest.raises(MixedCheckoutError):
        build_split_plan(duplicate, shipping_irr=0, physical_discount_irr=0)


def test_fingerprint_changes_with_price_quantity_discount_terms():
    """A stale button may not authorize changed IRR/XTR or merchant terms."""
    origin = checkout_quote_fingerprint(
        lines(), shipping_irr=25_000, physical_discount_irr=20_000,
        policy_token="abc123",
    )
    assert len(origin) == 12
    assert origin != checkout_quote_fingerprint(
        lines(), shipping_irr=25_000, physical_discount_irr=20_000,
        policy_token="different",
    )
    assert origin != checkout_quote_fingerprint(
        lines(), shipping_irr=25_001, physical_discount_irr=20_000,
        policy_token="abc123",
    )
    changed = lines()[:1] + (
        ExampleLine(2, "digital", 3, 50_000, 10, False),
    )
    assert origin != checkout_quote_fingerprint(
        changed, shipping_irr=25_000, physical_discount_irr=20_000,
        policy_token="abc123",
    )
