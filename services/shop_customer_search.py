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
from services.shop_customer_views import envelope, persist
from services.shop_model_registry import escape_like

_SEARCH_FIELDS = {
    "name": Product.name,
    "sku": Product.sku,
    "description": Product.description,
}
_SEARCH_PAGE_SIZE = 4
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


def _session(state: ShopCustomerChatState) -> dict | None:
    """Read the current search deadline independently of other forms."""
    value = envelope(state).get("search")
    if value is None and state.action == "product_search" and state.expires_at is not None:
        # Older rows already own a bounded search deadline.
        expiry = state.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        value = {"stage": "results" if state.query_text else "input", "expires": expiry.isoformat()}
    if not isinstance(value, dict) or value.get("stage") not in {"input", "results", "detail"}:
        return None
    try:
        expiry = datetime.fromisoformat(value["expires"])
    except (KeyError, TypeError, ValueError):
        return None
    return value if expiry.tzinfo is not None and expiry > datetime.now(timezone.utc) else None


def _stage(state: ShopCustomerChatState, stage: str) -> None:
    """Advance the search state without extending a parked address."""
    expires = datetime.now(timezone.utc) + _SEARCH_TTL
    data = envelope(state)
    data["search"] = {"stage": stage, "expires": expires.isoformat()}
    persist(state, data)
    if stage == "detail":
        state.action = "idle"
    else:
        state.action = "product_search"
        state.expires_at = expires


def clear_search(state: ShopCustomerChatState) -> bool:
    """End search while leaving unrelated cart and draft fields intact."""
    data = envelope(state)
    changed = bool(data.pop("search", None) is not None or state.query_text)
    if state.action == "product_search":
        state.action = "idle"
        changed = True
    if changed:
        state.query_text, state.query_field, state.page = None, "all", 0
        persist(state, data)
    return changed


def _prompt() -> BotReply:
    """Offer plain text first and show filters only on request."""
    return BotReply(
        "نام یا کد محصول را بنویسید.",
        _rows(
            InlineAction("فیلترهای جستجو", "ux:search:filters"),
            InlineAction("لغو جستجو", "ux:search:stop"),
            InlineAction("منوی اصلی", "shop:home"),
        ),
    )


async def _expired(db: AsyncSession, state: ShopCustomerChatState | None) -> BotReply:
    """Offer fresh search without renewing an expired result."""
    if state is not None and clear_search(state):
        await db.commit()
    return BotReply(
        "مهلت جستجو پایان یافته است. برای ادامه جستجوی تازه‌ای شروع کنید.",
        _rows(InlineAction("جستجوی دوباره", "ux:search"), InlineAction("منوی اصلی", "shop:home")),
    )


async def start(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply:
    """Begin a fresh chat search with an optional field chooser."""
    from services.shop_address_wizard import park_address_draft

    state = await _state(db, context, event, create=True)
    park_address_draft(state)
    state.query_text, state.query_field, state.page, state.context_ref = None, "all", 0, None
    _stage(state, "input")
    await db.commit()
    return _prompt()


async def filters(db: AsyncSession, context: BotContext, event: InboundEvent) -> BotReply:
    """Expose the supported filters without forcing a choice."""
    state = await _state(db, context, event)
    if state is None or _session(state) is None:
        return await _expired(db, state)
    back = (
        InlineAction("بازگشت به نتایج", "ux:search:back") if state.query_text
        else InlineAction("بازگشت به جستجو", "ux:search")
    )
    return BotReply(
        "در کدام بخش محصول جستجو کنیم؟",
        _rows(
            InlineAction("همهٔ اطلاعات عمومی", "ux:search:field:all"),
            InlineAction("نام محصول", "ux:search:field:name"),
            InlineAction("کد محصول", "ux:search:field:sku"),
            InlineAction("توضیحات", "ux:search:field:description"),
            back,
        ),
    )


async def field(
    db: AsyncSession, context: BotContext, event: InboundEvent,
    *, field_name: str,
) -> BotReply:
    """Apply an approved filter to the current query or next text turn."""
    state = await _state(db, context, event)
    if state is None or _session(state) is None:
        return await _expired(db, state)
    if field_name not in permitted_search_fields():
        return BotReply("این فیلتر در دسترس نیست.", _prompt().rows)
    state.query_field = field_name
    if state.query_text:
        return await results(db, context, state, requested_page=0)
    _stage(state, "input")
    await db.commit()
    return _prompt()


async def results(
    db: AsyncSession, context: BotContext,
    state: ShopCustomerChatState, *, requested_page: int,
) -> BotReply:
    """Render the closest available result page under the current catalog ACL."""
    from services.shop_channel_catalog import CatalogFlow

    if not state.query_text or not search_text_valid(state.query_text):
        return _prompt()
    scope = await resolve_scope(db, bot_id=context.bot_id)
    if not scope.available:
        return BotReply(
            "محصولات این فروشگاه فعلاً در دسترس نیستند.",
            _rows(InlineAction("منوی اصلی", "shop:home")),
        )
    requested_page = min(max(0, requested_page), 10_000)
    query = state.query_text
    items, total, page = await query_products(
        db, context, query=query, field_name=state.query_field,
        page=requested_page + 1, page_size=_SEARCH_PAGE_SIZE,
    )
    if total and not items:
        # Eligibility may change between count and page reads.
        items, total, page = await query_products(
            db, context, query=query, field_name=state.query_field,
            page=requested_page + 1, page_size=_SEARCH_PAGE_SIZE,
        )
    page -= 1
    state.page = page if items else 0
    _stage(state, "results")
    await db.commit()
    if not items:
        return BotReply(
            f"برای «{query[:70]}» محصولی پیدا نشد.",
            _rows(
                InlineAction("جستجوی دوباره", "ux:search"),
                InlineAction("دیدن محصولات", "shop:list:0"),
                InlineAction("منوی اصلی", "shop:home"),
            ),
        )
    last_page = (total - 1) // _SEARCH_PAGE_SIZE
    controls = []
    if page:
        controls.append(InlineAction("صفحه قبل", f"ux:search:page:{page - 1}"))
    if page < min(last_page, 10_000):
        controls.append(InlineAction("صفحه بعد", f"ux:search:page:{page + 1}"))
    return CatalogFlow(bot_context=context).compact_products(
        items,
        title=f"نتایج «{query[:70]}» · صفحه {page + 1} از {last_page + 1}",
        target=lambda product: f"shop:item:{product.id}:search",
        controls=tuple(controls),
        footer=(
            InlineAction("فیلترهای جستجو", "ux:search:filters"),
            InlineAction("لغو جستجو", "ux:search:stop"),
            InlineAction("منوی اصلی", "shop:home"),
        ),
    )


async def text_search(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply | None:
    """Consume free text only while the exact shopper is still in search."""
    state = await _state(db, context, event)
    if state is None or state.action != "product_search":
        return None
    if _session(state) is None:
        return await _expired(db, state)
    if not search_text_valid(event.text or ""):
        return BotReply("برای جستجو، نام یا کدی با ۲ تا ۱۰۰ نویسه بنویسید.", _prompt().rows)
    state.query_text = event.text.strip()
    return await results(db, context, state, requested_page=0)


async def paginate(
    db: AsyncSession, context: BotContext, event: InboundEvent,
    *, page: int | None = None,
) -> BotReply:
    """Restore the retained page or select an adjacent one within the same search."""
    state = await _state(db, context, event)
    if state is None or _session(state) is None or not state.query_text:
        return await _expired(db, state)
    return await results(db, context, state, requested_page=state.page if page is None else page)


async def open_result(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply | None:
    """Keep query and page while disarming text entry during product details."""
    state = await _state(db, context, event)
    if state is None or _session(state) is None or not state.query_text:
        return await _expired(db, state)
    _stage(state, "detail")
    await db.commit()
    return None


async def stop(
    db: AsyncSession, context: BotContext, event: InboundEvent,
) -> BotReply:
    """Clear only this shopper's ephemeral search state."""
    state = await _state(db, context, event)
    if state is not None and clear_search(state):
        await db.commit()
    return BotReply("جستجو متوقف شد.", _rows(InlineAction("منوی اصلی", "shop:home")))


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
