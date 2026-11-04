"""Offline customer terms navigation and explicit checkout consent tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_checkout_policy import ShopStoreCheckoutPolicy
from models.shop_content import ShopOrder
from models.shop_multibot import DEFAULT_STORE_ID
from services.shop_cart import ShopCartFlow
from services.shop_customer_experience import CustomerExperienceFlow
from tests.test_shared_cart import db, event, seed


def actions(reply):
    """Flatten the actual inline actions returned to either provider."""
    return [action for row in reply.rows for action in row]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize(
    "terms_text",
    [
        ("بند فروش؛ شرایط خرید.\n" * 400)[:5997] + "آخر",
        "📦" * 6000,
    ],
    ids=["persian-policy", "astral-policy"],
)
async def test_all_terms_are_reachable_without_truncation(db, platform, terms_text):
    """A 6000-character policy remains complete, ordered and provider-bounded."""
    policy = db.session.get(ShopStoreCheckoutPolicy, DEFAULT_STORE_ID)
    policy.terms_text = terms_text
    db.session.commit()
    flow = CustomerExperienceFlow()
    reply = await flow.reply(event(platform, text="/terms"), db)
    contents = []
    page = 0
    while True:
        assert len(reply.text.encode("utf-16-le")) // 2 <= 4096
        assert "fixture-v1" in reply.text.split("\n\n", 1)[0]
        contents.append(reply.text.split("\n\n", 1)[1])
        for action in actions(reply):
            assert len(action.callback_data.encode("utf-8")) <= 64
        following = [
            action for action in actions(reply)
            if action.callback_data.startswith("ux:terms:")
            and action.callback_data.split(":")[3] == str(page + 1)
        ]
        if not following:
            break
        assert page < 4, "A bounded policy must not create an unending pager."
        reply = await flow.reply(
            event(platform, callback=following[0].callback_data), db,
        )
        page += 1
    assert "".join(contents) == terms_text
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_checkout_terms_view_returns_to_same_explicit_consent(db, platform):
    """Reading the policy creates no order and preserves the quoted consent."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    cart = ShopCartFlow()
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    preview = await cart.reply(event(platform, callback="shop:checkout"), db)
    consent = next(
        action.callback_data for action in actions(preview)
        if action.callback_data.startswith("shop:place:")
    )
    terms_actions = [
        action for action in actions(preview)
        if action.callback_data.startswith("ux:terms:")
    ]
    assert len(terms_actions) == 1
    terms = await CustomerExperienceFlow().reply(
        event(platform, callback=terms_actions[0].callback_data), db,
    )
    assert "fixture-v1" in terms.text
    assert not any(
        action.callback_data.startswith("shop:place:")
        for action in actions(terms)
    )
    assert db.session.scalars(select(ShopOrder)).all() == []
    review_action = next(
        action for action in actions(terms)
        if action.callback_data == "shop:checkout"
    )
    refreshed = await cart.reply(
        event(platform, callback=review_action.callback_data), db,
    )
    assert consent in [action.callback_data for action in actions(refreshed)]
    await cart.reply(event(platform, callback=consent), db)
    order = db.session.scalars(select(ShopOrder)).one()
    assert order.terms_version_snapshot == "fixture-v1"
    assert order.terms_accepted_at is not None
    assert order.status == "pending_review"
    assert order.telegram_payment_charge_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_changed_terms_invalidate_old_paging_and_checkout_proof(db, platform):
    """Even an edit retaining the public version expires old view and consent."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    cart = ShopCartFlow()
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    preview = await cart.reply(event(platform, callback="shop:checkout"), db)
    consent = next(
        action.callback_data for action in actions(preview)
        if action.callback_data.startswith("shop:place:")
    )
    terms_actions = [
        action for action in actions(preview)
        if action.callback_data.startswith("ux:terms:")
    ]
    assert terms_actions
    policy = db.session.get(ShopStoreCheckoutPolicy, DEFAULT_STORE_ID)
    policy.terms_text = "شرایط فروش جدید؛ این متن با شرایط قبلی تفاوت دارد."
    db.session.commit()
    expired_view = await CustomerExperienceFlow().reply(
        event(platform, callback=terms_actions[0].callback_data), db,
    )
    assert "تغییر" in expired_view.text
    assert any(
        action.callback_data == "ux:terms" for action in actions(expired_view)
    )
    await cart.reply(event(platform, callback=consent), db)
    assert db.session.scalars(select(ShopOrder)).all() == []
