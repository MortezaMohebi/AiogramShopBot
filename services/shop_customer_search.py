"""Store-scoped, Bot-verified customer catalog search.

Only four public Product fields are searchable, and the active bot catalog
entitlement is always applied. No user text is interpolated into SQL source.
Search session state is per (bot_id, user_id) and expires after inactivity.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_content import Product
from models.shop_customer_navigation import ShopCustomerChatState
from services.shop_bot_catalog_acl import (
    CatalogScope, permitted_product_clause, resolve_scope,
)
from services.shop_bot_context import BotContext
from services.shop_model_registry import escape_like

_SEARCH_FIELDS = {
    "name": Product.name,
    "sku": Product.sku,
    "description": Product.description,
}
_SEARCH_PAGE_SIZE = 1
_SEARCH_TTL = timedelta(minutes=15)


def permitted_search_fields() -> tuple[str, ...]:
    """Expose only published customer Product attributes."""
    return ("all", "name", "sku", "description")


def search_key(*, bot_id: str, user_id: int) -> tuple[str, int]:
    """Never identify a search session by bare numeric user ID."""
    if not bot_id or type(user_id) is not int or user_id <= 0:
        raise ValueError("Invalid authenticated search owner.")
    return bot_id, user_id


def search_text_valid(value: str) -> bool:
    """Accept bounded printable Unicode query text including Farsi."""
    return (
        isinstance(value, str)
        and 2 <= len(value.strip()) <= 100
        and all(char.isprintable() for char in value)
    )


def _rows(*actions: InlineAction) -> tuple[tuple[InlineAction, ...], ...]:
    """Keep every callback short and valid on both messaging platforms."""
    return tuple((action,) for action in actions)


async def _state(
    db: AsyncSession, context: BotContext, event: InboundEvent,
    *, create: bool = False,
) -> ShopCustomerChatState | None:
    """Retrieve only this authenticated Bot/customer's ephemeral form."""
    key = search_key(bot_id=context.bot_id, user_id=event.user_id)
    state = await db.get(ShopCustomerChatState, key)
    if state is not None and state.store_id != context.store_id:
        raise ValueError("Customer chat state Store ownership mismatch.")
    if state is None and create:
        try:
            async with db.begin_nested():
                state = ShopCustomerChatState(
                    bot_id=context.bot_id,
                    platform_user_id=event.user_id,
                    store_id=context.store_id,
                    action="idle", query_field="all",
                    expires_at=datetime.now(timezone.utc) + _SEARCH_TTL,
                )
                db.add(state)
                await db.flush()
        except IntegrityError:
            state = await db.get(ShopCustomerChatState, key)
            if state is None:
                raise ValueError("Customer chat state creation failed.") from None
    return state


async def start(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply:
    """Begin chat search, optionally selecting a public Search field."""
    state = await _state(db, context, event, create=True)
    state.action = "product_search"
    state.page = 0
    state.query_text = None
    state.query_field = "all"
    state.expires_at = datetime.now(timezone.utc) + _SEARCH_TTL
    await db.commit()
    return BotReply(
        "🔎 نام یا کد محصول را بنویسید.\n"
        "می‌توانید جستجو را به یک فیلد محدود کنید. برای خروج /cancel را بزنید.",
        _rows(
            InlineAction("تمام فیلدهای عمومی", "ux:search:field:all"),
            InlineAction("نام محصول", "ux:search:field:name"),
            InlineAction("کد SKU", "ux:search:field:sku"),
            InlineAction("توضیحات", "ux:search:field:description"),
            InlineAction("🏠 منوی اصلی", "shop:home"),
        ),
    )


async def field(
    db: AsyncSession, context: BotContext, event: InboundEvent,
    *, field_name: str,
) -> BotReply:
    """Set only a registry-approved public query column."""
    if field_name not in permitted_search_fields():
        return BotReply("فیلد جستجوی انتخاب‌شده مجاز نیست.")
    state = await _state(db, context, event, create=True)
    state.action = "product_search"
    state.query_text = None
    state.query_field = field_name
    state.page = 0
    state.expires_at = datetime.now(timezone.utc) + _SEARCH_TTL
    await db.commit()
    return BotReply(
        "عبارت جستجو را برای فیلد انتخاب‌شده ارسال کنید.",
        _rows(
            InlineAction("🔎 تغییر فیلد", "ux:search"),
            InlineAction("🏠 منوی اصلی", "shop:home"),
        ),
    )


async def results(
    db: AsyncSession, context: BotContext,
    state: ShopCustomerChatState, *, requested_page: int,
) -> BotReply:
    """Search paginated published Products through current Bot ACL."""
    if (
        not state.query_text
        or not search_text_valid(state.query_text)
        or requested_page < 0 or requested_page > 10_000
    ):
        return BotReply("ابتدا یک عبارت جستجوی معتبر وارد کنید.")
    scope = await resolve_scope(db, bot_id=context.bot_id)
    if not scope.available:
        return BotReply("کاتالوگ این بات در حال حاضر فعال نیست.")
    items, total, page = await query_products(
        db,
        context,
        query=state.query_text,
        field_name=state.query_field,
        page=requested_page + 1,
        page_size=_SEARCH_PAGE_SIZE,
    )
    page -= 1
    if total == 0:
        return BotReply(
            f"برای «{state.query_text[:70]}» نتیجه‌ای پیدا نشد.\n"
            "عبارت را تغییر دهید یا دسته‌بندی‌ها را ببینید.",
            _rows(
                InlineAction("🔎 جستجوی دوباره", "ux:search"),
                InlineAction("🗂 دسته‌بندی‌ها", "shop:categories"),
                InlineAction("🆘 پشتیبانی", "ux:support"),
            ),
        )
    last_page = (total - 1) // _SEARCH_PAGE_SIZE
    controls = []
    if page:
        controls.append(InlineAction("⬅ قبلی", f"ux:search:page:{page - 1}"))
    if page < last_page:
        controls.append(InlineAction("بعدی ➡", f"ux:search:page:{page + 1}"))
    state.page = page
    state.expires_at = datetime.now(timezone.utc) + _SEARCH_TTL
    await db.commit()
    from services.shop_channel_catalog import CatalogFlow

    card = await CatalogFlow(bot_context=context)._product(
        db, items[0].id, context.platform.value, scope,
        navigation=tuple(controls),
    )
    return BotReply(
        f"🔎 {page + 1} از {total} نتیجه برای «{state.query_text[:70]}»\n{card.text}",
        card.rows, card.attachments, card.preview,
    )


async def text_search(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply | None:
    """Consume free text only when the exact Bot FSM awaits a search term."""
    state = await _state(db, context, event)
    if state is None or state.action != "product_search":
        return None
    now = datetime.now(timezone.utc)
    valid_until = state.expires_at
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    if valid_until <= now:
        state.action = "idle"
        state.query_text = None
        await db.commit()
        return BotReply(
            "زمان جستجو پایان یافته؛ دوباره جستجو را آغاز کنید.",
            _rows(InlineAction("🔎 جستجوی دوباره", "ux:search")),
        )
    if not search_text_valid(event.text or ""):
        return BotReply(
            "عبارت جستجو باید ۲ تا ۱۰۰ کاراکتر قابل‌نمایش باشد.",
            _rows(InlineAction("لغو جستجو", "ux:search:stop")),
        )
    state.query_text = event.text.strip()
    state.page = 0
    return await results(db, context, state, requested_page=0)


async def paginate(
    db: AsyncSession, context: BotContext, event: InboundEvent,
    *, page: int,
) -> BotReply:
    """Read a bounded search page only for the current bot user."""
    state = await _state(db, context, event)
    if state is None or state.action != "product_search":
        return BotReply(
            "جستجوی فعال پیدا نشد.",
            _rows(InlineAction("🔎 جستجوی جدید", "ux:search")),
        )
    return await results(db, context, state, requested_page=page)


async def stop(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply:
    """Clear only this Bot/user's ephemeral search state."""
    state = await _state(db, context, event)
    if state is not None:
        state.action = "idle"
        state.query_text = None
        await db.commit()
    return BotReply(
        "جستجو متوقف شد.",
        _rows(InlineAction("🏠 منوی اصلی", "shop:home")),
    )


async def query_products(
    db: AsyncSession,
    context: BotContext,
    *,
    query: str = "",
    field_name: str = "all",
    page: int = 1,
    page_size: int = 20,
    category_id: int | None = None,
) -> tuple[list[Product], int, int]:
    """Read typed paginated products using the same customer search and ACL rules."""
    if (
        field_name not in permitted_search_fields()
        or not 1 <= page <= 10001
        or not 1 <= page_size <= 50
        or (query and not search_text_valid(query))
    ):
        raise ValueError("Invalid bounded catalog search.")
    scope = await resolve_scope(db, bot_id=context.bot_id)
    constraints = [
        permitted_product_clause(scope),
        Product.store_id == context.store_id,
    ]
    if query:
        term = "%" + escape_like(query.strip()) + "%"
        fields = (
            _SEARCH_FIELDS.values()
            if field_name == "all"
            else (_SEARCH_FIELDS[field_name],)
        )
        constraints.append(or_(*(column.ilike(term, escape="\\") for column in fields)))
    if category_id is not None:
        constraints.append(Product.category_id == category_id)
    total = int(
        await db.scalar(select(func.count()).select_from(Product).where(*constraints))
        or 0
    )
    actual_page = min(page, max(1, (total + page_size - 1) // page_size))
    items = (
        await db.scalars(
            select(Product)
            .where(*constraints)
            .order_by(
                Product.position,
                Product.id,
            )
            .offset((actual_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(items), total, actual_page
