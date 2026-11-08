"""Offline customer terms navigation and explicit checkout consent tests."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.schema_support import test_bot_context
from channels.contracts import Platform
from models.shop_checkout import ShopCart
from models.shop_checkout_policy import ShopStoreCheckoutPolicy
from models.shop_content import ShopOrder
from models.shop_multibot import DEFAULT_STORE_ID
from models.shop_payment import ShopPaymentAttempt
from models.shop_store_commerce import ShopBotCommercePolicy
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
    flow = CustomerExperienceFlow(bot_context=test_bot_context(platform))
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
@pytest.mark.parametrize("mode", ["manual", "instant"])
async def test_checkout_terms_view_returns_to_same_explicit_consent(db, platform, mode):
    """Reading the policy creates no order and preserves the quoted consent."""
    product, _ = seed(db)
    product.requires_shipping = False
    policy = db.session.get(ShopStoreCheckoutPolicy, DEFAULT_STORE_ID)
    policy.mode = mode
    policy.terms_text = "📦" * 5997 + "آخر"
    db.session.commit()
    cart = ShopCartFlow(bot_context=test_bot_context(platform))
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    preview = await cart.reply(event(platform, callback="shop:checkout"), db)
    assert "بدون ارسال" in preview.text
    assert "/terms" not in preview.text
    consent = next(
        action.callback_data for action in actions(preview)
        if action.callback_data.startswith("shop:place:")
    )
    terms_actions = [
        action for action in actions(preview)
        if action.callback_data.startswith("ux:terms:")
    ]
    assert len(terms_actions) == 1
    assert [a.callback_data for a in actions(preview)] == [
        consent, terms_actions[0].callback_data, "shop:cart",
    ]
    experience = CustomerExperienceFlow(bot_context=test_bot_context(platform))
    terms = await experience.reply(event(platform, callback=terms_actions[0].callback_data), db)
    parts = []
    while True:
        assert "fixture-v1" in terms.text
        assert len(terms.text.encode("utf-16-le")) // 2 <= 4096
        assert not any(a.callback_data.startswith("shop:place:") for a in actions(terms))
        review_action = next(a for a in actions(terms) if "بازگشت به بررسی سفارش" in a.label)
        refreshed = await cart.reply(event(platform, callback=review_action.callback_data), db)
        assert refreshed == preview
        parts.append(terms.text.split("\n\n", 1)[1])
        following = next((a for a in actions(terms) if a.label == "صفحه بعد"), None)
        if following is None:
            break
        terms = await experience.reply(event(platform, callback=following.callback_data), db)
    assert "".join(parts) == policy.terms_text
    await cart.reply(event(platform, callback="shop:cart"), db)
    assert db.session.scalars(select(ShopOrder)).all() == []
    assert db.session.scalars(select(ShopPaymentAttempt)).all() == []
    assert db.session.scalar(select(ShopCart)).revision == int(consent.split(":")[3])
    await cart.reply(event(platform, callback=consent), db)
    order = db.session.scalars(select(ShopOrder)).one()
    assert order.terms_version_snapshot == "fixture-v1"
    assert order.terms_accepted_at is not None
    assert order.status == ("approved_unpaid" if mode == "instant" else "pending_review")
    assert order.telegram_payment_charge_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_order_detail_uses_customer_labels_and_sale_unit(db, platform):
    """An unpaid order shows its business state without internal identifiers."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    context = test_bot_context(platform)
    cart = ShopCartFlow(bot_context=context)
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    preview = await cart.reply(event(platform, callback="shop:checkout"), db)
    consent = next(
        action.callback_data for action in actions(preview)
        if action.callback_data.startswith("shop:place:")
    )
    await cart.reply(event(platform, callback=consent), db)
    order = db.session.scalars(select(ShopOrder)).one()

    detail = await CustomerExperienceFlow(bot_context=context).reply(
        event(platform, callback=f"ux:order:detail:{order.id}"), db,
    )
    assert "وضعیت: در انتظار بررسی فروشنده" in detail.text
    assert "مبلغ سفارش:" in detail.text
    assert "1 عدد" in detail.text
    assert "بات مبدأ" not in detail.text
    assert "pending_review" not in detail.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_changed_terms_invalidate_old_paging_and_checkout_proof(db, platform):
    """Even an edit retaining the public version expires old view and consent."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    cart = ShopCartFlow(bot_context=test_bot_context(platform))
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
    expired_view = await CustomerExperienceFlow(
        bot_context=test_bot_context(platform)
    ).reply(
        event(platform, callback=terms_actions[0].callback_data),
        db,
    )
    assert "تغییر" in expired_view.text
    refreshed = next(action.callback_data for action in actions(expired_view)
                     if action.callback_data.startswith("shop:place:"))
    assert refreshed != consent
    await cart.reply(event(platform, callback=consent), db)
    assert db.session.scalars(select(ShopOrder)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_terms_recovery_distinguishes_bad_page_quote_and_unavailability(db, platform):
    """Terms failures retain their checkout destination and never accept an order."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    context = test_bot_context(platform)
    cart = ShopCartFlow(bot_context=context)
    experience = CustomerExperienceFlow(bot_context=context)

    empty = await cart.reply(event(platform, callback="shop:checkout"), db)
    assert "خالی" in empty.text
    assert db.session.scalars(select(ShopCart)).all() == []
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    preview = await cart.reply(event(platform, callback="shop:checkout"), db)
    original = next(a.callback_data for a in actions(preview)
                    if a.callback_data.startswith("shop:place:"))
    origin = next(a.callback_data for a in actions(preview)
                  if a.callback_data.startswith("ux:terms:"))
    terms = await experience.reply(event(platform, callback=origin), db)
    back = next(a.callback_data for a in actions(terms)
                if "بازگشت به بررسی سفارش" in a.label)
    invalid = origin.split(":")
    invalid[3] = "999"
    invalid_page = await experience.reply(event(platform, callback=":".join(invalid)), db)
    assert "صفحه" in invalid_page.text
    assert any(a.callback_data.startswith("shop:place:") for a in actions(invalid_page))

    product.price = 2000
    db.session.commit()
    repriced = await cart.reply(event(platform, callback=back), db)
    assert "تغییر" in repriced.text and "2,000 ریال" in repriced.text
    assert original not in [a.callback_data for a in actions(repriced)]
    await cart.reply(event(platform, callback=original), db)

    policy = db.session.get(ShopStoreCheckoutPolicy, DEFAULT_STORE_ID)
    policy.terms_text = ""
    db.session.commit()
    unavailable = await experience.reply(event(platform, callback=origin), db)
    assert "شرایط" in unavailable.text
    assert "ux:support" in [a.callback_data for a in actions(unavailable)]

    db.session.get(ShopBotCommercePolicy, context.bot_id).cart_enabled = False
    db.session.commit()
    disabled = await cart.reply(event(platform, callback=back), db)
    assert "غیرفعال" in disabled.text
    assert "shop:cart" not in [a.callback_data for a in actions(disabled)]
    assert "shop:home" in [a.callback_data for a in actions(disabled)]
    assert db.session.scalars(select(ShopOrder)).all() == []
    assert db.session.scalars(select(ShopPaymentAttempt)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_checkout_proof_cannot_be_used_by_another_shopper(db, platform):
    """A current terms or order proof is never a substitute for cart ownership."""
    product, _ = seed(db)
    product.requires_shipping = False
    db.session.commit()
    context = test_bot_context(platform)
    from tests.schema_support import seed_customer

    seed_customer(db.session, platform, user_id=202)
    db.session.commit()
    cart = ShopCartFlow(bot_context=context)
    await cart.reply(event(platform, callback=f"shop:add:{product.id}"), db)
    review = await cart.reply(event(platform, callback="shop:checkout"), db)
    accept, terms, _ = actions(review)
    unavailable = await CustomerExperienceFlow(bot_context=context).reply(
        event(platform, callback=terms.callback_data, uid=202), db,
    )
    assert "خالی" in unavailable.text
    await cart.reply(event(platform, callback=accept.callback_data, uid=202), db)
    assert db.session.scalars(select(ShopOrder)).all() == []
    assert db.session.scalars(select(ShopPaymentAttempt)).all() == []
