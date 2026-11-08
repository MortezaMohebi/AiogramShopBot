"""Bale checkout cannot create an order its delivery paths cannot fulfill."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from tests.schema_support import test_bot_context
from channels.contracts import Platform
from models.shop_content import ShopOrder
from models.shop_digital_delivery import ShopDigitalLicense
from services.shop_cart import ShopCartFlow
from tests.test_shared_cart import db, event, seed


def digital_supply(db, product):
    """Provide real available inventory; no license is decrypted or delivered."""
    product.product_type = "digital"
    product.requires_shipping = False
    product.digital_delivery_mode = "license"
    db.add(ShopDigitalLicense(
        id=str(uuid4()), store_id=product.store_id, product_id=product.id,
        code_fingerprint=uuid4().hex * 2, ciphertext="isolated-unused-inventory",
    ))


@pytest.mark.asyncio
async def test_bale_mixed_preview_requires_two_separate_orders(db):
    """A stocked physical+digital basket must not expose a place-order callback."""
    physical, digital = seed(db)
    physical.requires_shipping = False
    digital_supply(db, digital)
    await db.commit()
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    for product in (physical, digital):
        await flow.reply(event(Platform.BALE, callback=f"shop:add:{product.id}"), db)
    preview = await flow.reply(event(Platform.BALE, callback="shop:checkout"), db)
    assert "جدا" in preview.text
    assert not any(
        action.callback_data.startswith("shop:place:")
        for row in preview.rows for action in row
    )
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
async def test_bale_old_confirmation_rechecks_a_now_mixed_cart(db):
    """Changing a product type after approval cannot create an unfulfillable order."""
    physical, changed = seed(db)
    physical.requires_shipping = changed.requires_shipping = False
    await db.commit()
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    for product in (physical, changed):
        await flow.reply(event(Platform.BALE, callback=f"shop:add:{product.id}"), db)
    preview = await flow.reply(event(Platform.BALE, callback="shop:checkout"), db)
    confirmation = next(
        action.callback_data for row in preview.rows for action in row
        if action.callback_data.startswith("shop:place:")
    )
    digital_supply(db, changed)
    await db.commit()
    refused = await flow.reply(event(Platform.BALE, callback=confirmation), db)
    assert "جدا" in refused.text
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("digital", [False, True])
async def test_bale_uniform_baskets_still_allow_explicit_checkout(db, digital):
    """The mixed guard preserves physical-only and digital-only purchases."""
    products = seed(db)
    for product in products:
        product.requires_shipping = False
        if digital:
            digital_supply(db, product)
    await db.commit()
    flow = ShopCartFlow(bot_context=test_bot_context(Platform.BALE))
    for product in products:
        await flow.reply(event(Platform.BALE, callback=f"shop:add:{product.id}"), db)
    preview = await flow.reply(event(Platform.BALE, callback="shop:checkout"), db)
    assert any(
        action.callback_data.startswith("shop:place:")
        for row in preview.rows for action in row
    )
