"""Paid digital file version pinning and multi-currency quote freshness."""

import pytest

from services.shop_digital_rules import (
    DeliveryPolicyError, validate_pinned_asset,
)
from services.shop_mixed_checkout import (
    checkout_quote_fingerprint, MixedCheckoutError,
)


def test_retired_private_file_is_still_bound_to_the_old_paid_order():
    """Replacement files must never silently fulfill an earlier purchase."""
    assert validate_pinned_asset(
        expected_asset_id="asset-old", actual_asset_id="asset-old",
        expected_store_id="store-a", actual_store_id="store-a",
        expected_product_id=10, actual_product_id=10, asset_exists=True,
    )
    with pytest.raises(DeliveryPolicyError):
        validate_pinned_asset(
            expected_asset_id="asset-old", actual_asset_id="asset-new",
            expected_store_id="store-a", actual_store_id="store-a",
            expected_product_id=10, actual_product_id=10, asset_exists=True,
        )


def test_cross_store_file_version_is_not_fulfilled():
    """An ID from another Store is not a valid digital purchase snapshot."""
    with pytest.raises(DeliveryPolicyError):
        validate_pinned_asset(
            expected_asset_id="asset-old", actual_asset_id="asset-old",
            expected_store_id="store-a", actual_store_id="store-b",
            expected_product_id=10, actual_product_id=10, asset_exists=True,
        )


def test_quote_fingerprint_detects_replaced_private_file():
    """A newly uploaded private file invalidates an old Checkout callback."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class Item:
        """Tiny product-like line with exact integer prices."""

        product_id: int
        product_type: str
        quantity: int
        unit_price_irr: int
        unit_price_stars: int | None
        requires_shipping: bool

    lines = [
        Item(1, "physical", 2, 10_000, None, True),
        Item(2, "digital", 1, 0, 9, False),
    ]
    def fingerprint(asset_id: str) -> str:
        """Create one quote proof differing only in private file version."""
        return checkout_quote_fingerprint(
            lines, shipping_irr=1000, physical_discount_irr=0,
            policy_token="same-terms", asset_ids={2: asset_id},
        )

    assert fingerprint("a" * 36) != fingerprint("b" * 36)
    with pytest.raises(MixedCheckoutError):
        checkout_quote_fingerprint(
            lines, shipping_irr=1000, physical_discount_irr=0,
            policy_token="same-terms", asset_ids={999: "a" * 36},
        )
