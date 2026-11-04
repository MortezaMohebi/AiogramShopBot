"""Real dispatcher navigation cannot leave private/shared cart forms active."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_checkout import ShopCart, ShopCartInputSession
from models.shop_customer_account_data import ShopCustomerAddress
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_customer_support import ShopSupportMessage
from models.shop_store_commerce import ShopStoreCommercePolicy
from services.shop_multibot_dispatch import dispatch
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_identity import register_customer
from tests.test_beta_paused_customer_support import NativeClient, raw
from tests.test_shared_cart import AsyncDatabase, db, seed


class FormDatabase(AsyncDatabase):
    """Expose actual row-lock arguments for shared cart form requests."""

    async def get(self, model, key, **kwargs):
        """Forward primary-key ownership and locking to the real ORM."""
        return self.session.get(model, key, **kwargs)


async def setup_dispatch(db, monkeypatch, platform):
    """Use real registered identities, cart/search services and native sends."""
    wrapped = FormDatabase(db.session)
    scope = await resolve_legacy_bot_context(wrapped, authenticated_platform=platform)
    await register_customer(wrapped, platform=platform, platform_user_id=101)

    @asynccontextmanager
    async def sessions():
        """Keep dispatcher writes on the isolated relational database."""
        yield wrapped

    monkeypatch.setattr("services.shop_multibot_dispatch.session_maker", sessions)
    return replace(scope, status="active"), NativeClient()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("form", ["address", "coupon"])
async def test_home_search_cannot_be_consumed_by_an_old_cart_form(
    db, monkeypatch, platform, form,
):
    """Cart form → Home → Search must search rather than save a shipping value."""
    product, _ = seed(db)
    product.name = "گوشی ویژه آزمایشی"
    db.session.commit()
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback=f"shop:{form}"))
    await dispatch(scope, native, raw(callback="shop:home"))
    await dispatch(scope, native, raw(callback="ux:search"))
    await dispatch(scope, native, raw(message=product.name))
    cart = db.session.scalars(select(ShopCart)).one()
    state = db.session.get(ShopCustomerChatState, (scope.bot_id, 101))
    assert cart.awaiting_input is None and cart.shipping_address is None
    assert state.action == "product_search" and state.query_text == product.name
    delivered = native.messages[-1]
    if platform == Platform.TELEGRAM:
        actions = [
            button.callback_data
            for row in delivered["reply_markup"].inline_keyboard for button in row
        ]
    else:
        actions = [action.callback_data for row in delivered["rows"] for action in row]
    assert f"shop:item:{product.id}" in actions


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_cancel_clears_cart_before_a_new_support_form(db, monkeypatch, platform):
    """Cancelling a cart address also permits a later ticket body to reach support."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback="shop:address"))
    await dispatch(scope, native, raw(message="/cancel"))
    cart = db.session.scalars(select(ShopCart)).one()
    assert cart.awaiting_input is None
    await dispatch(scope, native, raw(callback="ux:ticket:topic:general"))
    body = "درخواست پشتیبانی پس از لغو نشانی خرید"
    await dispatch(scope, native, raw(message=body))
    assert db.session.scalars(select(ShopSupportMessage.body)).one() == body
    assert cart.shipping_address is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_new_account_form_clears_old_cart_coupon(db, monkeypatch, platform):
    """A saved-address form cannot be intercepted by an old coupon prompt."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback="shop:coupon"))
    await dispatch(scope, native, raw(callback="ux:address:new"))
    await dispatch(scope, native, raw(message=(
        "خانه|مشتری نمونه|09123456789|تهران|تهران|خیابان نمونه پلاک ۱۲|1234567890"
    )))
    assert db.session.query(ShopCustomerAddress).count() == 1
    assert db.session.scalars(select(ShopCart.awaiting_input)).one() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
async def test_shared_cart_navigation_clears_only_the_current_bot_form(
    db, monkeypatch, platform,
):
    """Linked Bots retain independent pending input for one shared Customer cart."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    other_platform = Platform.BALE if platform == Platform.TELEGRAM else Platform.TELEGRAM
    other = await resolve_legacy_bot_context(db, authenticated_platform=other_platform)
    identity = await register_customer(db, platform=platform, platform_user_id=101)
    peer = await register_customer(db, platform=other_platform, platform_user_id=101)
    peer.customer_id = identity.customer_id
    db.add(ShopStoreCommercePolicy(
        store_id=scope.store_id, cart_scope="customer", credit_scope="identity",
    ))
    await db.commit()
    await dispatch(replace(other, status="active"), native, raw(callback="shop:address"))
    await dispatch(scope, native, raw(callback="shop:coupon"))
    await dispatch(scope, native, raw(callback="ux:search"))
    current = db.session.get(ShopCartInputSession, (scope.bot_id, 101))
    untouched = db.session.get(ShopCartInputSession, (other.bot_id, 101))
    assert current.awaiting_input is None
    assert untouched.awaiting_input == "address"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
@pytest.mark.parametrize("entry", [
    "ux:search:field:name", "🔎 جستجوی محصول", "👤 حساب من", "🆘 پشتیبانی",
])
async def test_semantic_menu_aliases_end_old_cart_input(db, monkeypatch, platform, entry):
    """Stale search-field buttons and supported text menu labels also leave forms."""
    scope, native = await setup_dispatch(db, monkeypatch, platform)
    await dispatch(scope, native, raw(callback="shop:address"))
    await dispatch(
        scope, native,
        raw(callback=entry) if entry.startswith("ux:") else raw(message=entry),
    )
    cart = db.session.scalars(select(ShopCart)).one()
    assert cart.awaiting_input is None and cart.shipping_address is None
