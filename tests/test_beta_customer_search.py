"""Customer search and chat FSM regression cases for both Bot adapters."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from channels.contracts import Platform
from models.shop_customer_navigation import ShopCustomerChatState
from services.shop_customer_search import search_text_valid, search_key, permitted_search_fields
from tests.test_shared_cart import db


def test_query_validation_handles_persian_and_rejects_empty_or_control():
    """Customer product search accepts Persian strings but not unsafe input."""
    assert search_text_valid("فیلتر روغن ۲۰۲۶")
    assert search_text_valid("SKU-AB_2026")
    for invalid in ("", " ", "a", "\n", "a\x00b", "x" * 101):
        assert not search_text_valid(invalid)


def test_search_owner_scoped_per_bot_even_with_same_numeric_user_id():
    """A bot/user pair is a unique FSM owner; provider IDs never suffice."""
    a, b = "bot-a", "bot-b"
    assert search_key(bot_id=a, user_id=55) != search_key(bot_id=b, user_id=55)


def test_customer_search_only_allows_published_fields():
    """Admin-only ORM/finance attributes are not valid bot search fields."""
    assert set(permitted_search_fields()) == {"all", "name", "sku", "description"}
    assert "store_id" not in permitted_search_fields()
    assert "customer_id" not in permitted_search_fields()
    assert "provider_token" not in permitted_search_fields()



def actions(reply):
    """Expose the actual controls produced by the shared provider-neutral view."""
    return [action for row in reply.rows for action in row]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_filtered_search_back_preserves_page_and_clamps_after_stock_changes(db, platform):
    """A result detail carries the search origin without leaving text input armed."""
    from sqlalchemy import select
    from models.shop_content import Product
    from services.shop_channel_catalog import CatalogFlow
    from services.shop_customer_experience import CustomerExperienceFlow
    from tests.schema_support import allow_test_catalog, test_bot_context
    from tests.test_shared_cart import event

    db.session.add_all([
        Product(
            sku=f"SEARCH-{index}", name=f"فیلتر نمونه {index}", description="آزمایشی",
            price=1200, stock_quantity=3, is_published=True, requires_shipping=False,
            position=index,
        )
        for index in range(9)
    ])
    allow_test_catalog(db.session)
    db.session.commit()
    context = test_bot_context(platform)
    experience = CustomerExperienceFlow(bot_context=context)
    catalog = CatalogFlow(bot_context=context)
    initial = await experience.reply(event(platform, text="/search"), db)
    assert all("ux:search:field:" not in a.callback_data for a in actions(initial))
    assert any(a.callback_data == "ux:search:stop" for a in actions(initial))
    filters = next(a for a in actions(initial) if a.callback_data == "ux:search:filters")
    choices = await experience.reply(event(platform, callback=filters.callback_data), db)
    field = next(a for a in actions(choices) if a.callback_data == "ux:search:field:name")
    await experience.reply(event(platform, callback=field.callback_data), db)
    results = await experience.reply(event(platform, text="فیلتر نمونه"), db)
    following = next(a for a in actions(results) if a.callback_data == "ux:search:page:1")
    page = await experience.reply(event(platform, callback=following.callback_data), db)
    target = next(a for a in actions(page) if a.callback_data.endswith(":search"))
    detail = await catalog.reply(event(platform, callback=target.callback_data), db)
    back = next(a for a in actions(detail) if a.callback_data == "ux:search:back")
    state = db.session.get(ShopCustomerChatState, context.owner_key(101))
    assert state.action == "idle"
    assert await experience.reply(event(platform, text="این متن جستجوی تازه نیست"), db) is None
    assert await experience.reply(event(platform, callback=back.callback_data), db) == page
    assert (state.query_text, state.query_field, state.page) == ("فیلتر نمونه", "name", 1)
    for product in db.session.scalars(select(Product).where(Product.position >= 4)):
        product.is_published = False
    db.session.commit()
    await experience.reply(event(platform, callback=back.callback_data), db)
    assert state.page == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_expired_search_pager_never_renews_context(db, platform):
    """Old page and Back actions offer a fresh search instead of revealing old rows."""
    from services.shop_customer_experience import CustomerExperienceFlow
    from tests.schema_support import test_bot_context
    from tests.test_shared_cart import event, seed

    seed(db)
    context = test_bot_context(platform)
    experience = CustomerExperienceFlow(bot_context=context)
    await experience.reply(event(platform, text="/search"), db)
    await experience.reply(event(platform, text="محصول"), db)
    state = db.session.get(ShopCustomerChatState, context.owner_key(101))
    state.view_state = {
        **(state.view_state or {}),
        "search": {"stage": "results", "expires": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()},
    }
    db.session.commit()
    stale = await experience.reply(event(platform, callback="ux:search:page:0"), db)
    assert "پایان" in stale.text
    assert any(a.callback_data == "ux:search" for a in actions(stale))
    assert state.query_text is None
