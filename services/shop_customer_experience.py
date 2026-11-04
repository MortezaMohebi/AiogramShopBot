"""Single Telegram/Bale semantic customer interaction router.

Both native messaging adapters pass the same InboundEvent and verified
BotContext here. This router owns UX callbacks and delegates commerce
actions to the existing Catalog/Cart/Order/Wallet domain services.
"""

from __future__ import annotations

import re

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction, Platform
from models.shop_checkout import ShopCart, ShopCartInputSession
from models.shop_customer_navigation import ShopCustomerChatState
from services.shop_bot_context import BotContext, resolve_legacy_bot_context
from services import shop_customer_search as search


_SEARCH_PAGE = re.compile(r"ux:search:page:(0|[1-9][0-9]{0,3})\Z")
_SEARCH_FIELD = re.compile(r"ux:search:field:(all|name|sku|description)\Z")
_ORDER_DETAIL = re.compile(r"ux:order:detail:([1-9][0-9]{0,18})\Z")
_ORDER_TRACK = re.compile(r"ux:order:track:([1-9][0-9]{0,18})\Z")
_TERMS_PAGE = re.compile(
    r"ux:terms:([a-f0-9]{12}):(0|[1-9][0-9]{0,2})(:checkout)?\Z"
)
_TERMS_PAGE_UNITS = 3500


def _terms_pages(text: str) -> tuple[str, ...]:
    """Preserve the full policy in pages bounded by UTF-16 message units.

    Count astral characters twice so emoji-heavy terms also leave sufficient
    room for the version and page header on both messaging providers.
    """
    pages = []
    start = 0
    units = 0
    for position, character in enumerate(text):
        character_units = 2 if ord(character) > 0xFFFF else 1
        if units + character_units > _TERMS_PAGE_UNITS:
            pages.append(text[start:position])
            start = position
            units = 0
        units += character_units
    pages.append(text[start:])
    return tuple(pages)


def should_clear_chat_state(callback: str, text: str) -> bool:
    """End stale free-text forms when a customer navigates elsewhere.

    State is always scoped to (bot_id, platform_user_id); neither a generic
    chat ID nor a callback's supplied Store ID is used for this decision.
    """
    return (
        callback in {
            "shop:home", "shop:categories", "shop:cart", "shop:orders",
            "ux:account", "ux:support",
        }
        or callback.startswith("shop:item:")
        or text in {"/start", "/menu", "🏠 منوی اصلی"}
    )



async def clear_pending_on_navigation(
    db: AsyncSession, *, context: BotContext, event: InboundEvent,
) -> None:
    """End all owned form inputs before navigation or a different form starts.

    Cart input runs before account/search/support routing. Clear both private
    and shared cart input records alongside the UX state so an old address or
    coupon prompt cannot consume the next form's text. Shared input remains
    independently scoped to this authenticated Bot and user.
    """
    action = event.callback_data or ""
    text = (event.text or "").strip()
    starts_form = (
        action in {
            "shop:address", "shop:coupon", "ux:search", "ux:search:stop",
            "ux:address:new", "ux:phone",
        }
        or _SEARCH_FIELD.fullmatch(action) is not None
        or action.startswith(("ux:ticket:topic:", "ux:ticket:reply:"))
        or text in {
            "/cancel", "/search", "/address", "/ticket", "/support",
            "/paysupport", "/account", "/profile", "/wishlist",
            "🔎 جستجوی محصول", "👤 حساب من", "🆘 پشتیبانی",
        }
    )
    account_navigation = action.startswith((
        "ux:profile", "ux:addresses", "ux:address:choose:",
        "ux:address:delete:", "ux:wish", "ux:links", "ux:notifications",
        "ux:notify:", "ux:stock:", "ux:language", "ux:privacy",
        "ux:ticket:", "ux:tickets", "ux:terms",
        "shop:list:", "shop:category:", "shop:categories:",
    ))
    if not (
        should_clear_chat_state(action, text) or starts_form or account_navigation
    ):
        return
    changed = False
    state = await db.get(
        ShopCustomerChatState, (context.bot_id, event.user_id),
    )
    if state is not None:
        if state.store_id != context.store_id:
            raise ValueError("Customer chat Store mismatch.")
        if state.action != "idle" or state.context_ref or state.query_text:
            state.action = "idle"
            state.context_ref = None
            state.query_text = None
            changed = True
    private = await db.execute(update(ShopCart).where(
        ShopCart.store_id == context.store_id,
        ShopCart.bot_id == context.bot_id,
        ShopCart.platform == context.platform.value,
        ShopCart.platform_user_id == event.user_id,
        ShopCart.is_shared.is_(False),
        ShopCart.awaiting_input.is_not(None),
    ).values(awaiting_input=None))
    shared = await db.execute(update(ShopCartInputSession).where(
        ShopCartInputSession.bot_id == context.bot_id,
        ShopCartInputSession.platform_user_id == event.user_id,
        ShopCartInputSession.awaiting_input.is_not(None),
        ShopCartInputSession.cart_id.in_(select(ShopCart.id).where(
            ShopCart.store_id == context.store_id,
            ShopCart.is_shared.is_(True),
        )),
    ).values(awaiting_input=None))
    if changed or private.rowcount or shared.rowcount:
        await db.commit()


class CustomerExperienceFlow:
    """Apply the same semantic Home/Search/Account/Support routes to each bot."""

    def __init__(self, *, bot_context: BotContext | None = None) -> None:
        """Accept only a previously authenticated provider BotContext."""
        self.bot_context = bot_context

    async def context(
        self, db: AsyncSession, platform: Platform,
    ) -> BotContext:
        """Use a trusted provider binding, never a callback-selected bot."""
        if self.bot_context is not None:
            if self.bot_context.platform != platform:
                raise ValueError("Bot/provider mismatch.")
            return self.bot_context
        return await resolve_legacy_bot_context(
            db, authenticated_platform=platform,
        )

    async def reply(
        self, event: InboundEvent, db: AsyncSession,
    ) -> BotReply | None:
        """Route one private-chat command/callback without cross-Bot state."""
        action = event.callback_data or ""
        text = (event.text or "").strip()
        context = await self.context(db, event.platform)
        await clear_pending_on_navigation(
            db, context=context, event=event,
        )
        terms_page = _TERMS_PAGE.fullmatch(action)
        if action == "ux:terms" or text == "/terms" or terms_page:
            from services.shop_checkout_policy import checkout_rules

            policy = await checkout_rules(db, bot_id=context.bot_id)
            if len(policy.terms_text) < 12:
                return BotReply(
                    "شرایط فروش هنوز توسط مدیر ثبت نشده است. خرید جدید تا "
                    "تعریف قوانین فروش غیرفعال می‌ماند.",
                    ((InlineAction("🆘 پشتیبانی", "ux:support"),),),
                )
            if terms_page and terms_page.group(1) != policy.policy_token:
                return BotReply(
                    "شرایط خرید تغییر کرده است. متن فعلی را دوباره بررسی کنید.",
                    ((InlineAction("📜 مشاهده شرایط فعلی", "ux:terms"),),),
                )
            pages = _terms_pages(policy.terms_text)
            page = int(terms_page.group(2)) if terms_page else 0
            if page >= len(pages):
                return BotReply(
                    "این صفحه از شرایط خرید وجود ندارد. متن را دوباره باز کنید.",
                    ((InlineAction("📜 شرایط خرید", "ux:terms"),),),
                )
            origin = ":checkout" if terms_page and terms_page.group(3) else ""
            navigation = []
            if page:
                navigation.append(InlineAction(
                    "صفحه قبل",
                    f"ux:terms:{policy.policy_token}:{page - 1}{origin}",
                ))
            if page + 1 < len(pages):
                navigation.append(InlineAction(
                    "صفحه بعد",
                    f"ux:terms:{policy.policy_token}:{page + 1}{origin}",
                ))
            rows = [tuple(navigation)] if navigation else []
            if origin:
                # Returning to preview recomputes the existing quote proof;
                # reading any policy page never creates an order or consent.
                rows.append((InlineAction(
                    "بازگشت به بررسی سفارش", "shop:checkout",
                ),))
            rows.append((InlineAction("🏠 منوی اصلی", "shop:home"),))
            return BotReply(
                f"📜 شرایط خرید — نسخه {policy.terms_version}"
                f" — صفحه {page + 1} از {len(pages)}\n\n{pages[page]}",
                tuple(rows),
            )
        if action in {"ux:home"} or text in {"/menu", "🏠 منوی اصلی"}:
            from services.shop_channel_catalog import CatalogFlow

            return await CatalogFlow(
                bot_context=context,
            )._home(db, event.platform.value)

        if action == "ux:search" or text in {
            "/search", "🔎 جستجوی محصول",
        }:
            return await search.start(db, context, event)
        match = _SEARCH_FIELD.fullmatch(action)
        if match:
            return await search.field(
                db, context, event, field_name=match.group(1),
            )
        match = _SEARCH_PAGE.fullmatch(action)
        if match:
            return await search.paginate(
                db, context, event, page=int(match.group(1)),
            )
        if action == "ux:search:stop" or text == "/cancel":
            # A single cancel command stops the currently active bot-owned
            # form, regardless of whether it is address, ticket or search.
            state = await db.get(
                ShopCustomerChatState,
                (context.bot_id, event.user_id),
            )
            if state is not None:
                if state.store_id != context.store_id:
                    raise ValueError("Customer chat state Store mismatch.")
                state.action = "idle"
                state.context_ref = None
                state.query_text = None
                await db.commit()
            return BotReply(
                "عملیات متوقف شد.",
                ((InlineAction("🏠 منوی اصلی", "shop:home"),),),
            )

        detail = _ORDER_DETAIL.fullmatch(action)
        tracking = _ORDER_TRACK.fullmatch(action)
        if detail or tracking:
            from sqlalchemy import select

            from models.shop_checkout import ShopOrderLine
            from models.shop_content import ShopOrder
            from services.shop_customer_account import customer_for_bot
            from services.shop_customer_orders import order_visible_to_customer
            from services.shop_fulfillment import customer_tracking

            try:
                _, customer = await customer_for_bot(
                    db, context, platform_user_id=event.user_id,
                )
            except ValueError:
                return BotReply("برای مشاهده سفارش ابتدا /start را اجرا کنید.")
            order_id = int((detail or tracking).group(1))
            order = await order_visible_to_customer(
                db, store_id=context.store_id,
                customer_id=customer.id, order_id=order_id,
            )
            if order is None:
                return BotReply("سفارش متعلق به این حساب پیدا نشد.")
            if tracking:
                result = await customer_tracking(db, order=order)
                if result["status"] == "not_started":
                    return BotReply(
                        result["message"],
                        ((InlineAction("📦 سفارش", f"ux:order:detail:{order.id}"),),),
                    )
                timeline = "\n".join(
                    f"• {item['status']} — {item['time'][:16]}"
                    for item in result.get("events", [])
                )
                return BotReply(
                    f"🚚 پیگیری سفارش #{order.id}\n"
                    f"وضعیت: {result['status']}\n"
                    f"حمل‌کننده: {result.get('carrier') or 'ثبت نشده'}\n"
                    f"کد رهگیری: {result.get('tracking_code') or 'ثبت نشده'}\n"
                    f"{timeline}"[:4096],
                    ((InlineAction("📦 جزئیات سفارش", f"ux:order:detail:{order.id}"),),),
                )
            rows = (await db.scalars(select(ShopOrderLine).where(
                ShopOrderLine.order_id == order.id,
            ).order_by(ShopOrderLine.id).limit(40))).all()
            details = [
                f"📦 سفارش #{order.id}",
                f"وضعیت: {order.status}",
                (
                    f"مبلغ تأییدشده: {order.total_stars_snapshot} Stars (XTR)"
                    if order.platform == "telegram"
                    and order.total_stars_snapshot is not None
                    else f"مبلغ قطعی: {order.total_irr:,} ریال"
                ),
                f"بات مبدأ: {order.bot_id[:8]}",
                f"نسخه شرایط خرید: {order.terms_version_snapshot or 'ثبت نشده'}",
            ]
            for item in rows:
                details.append(
                    f"• {item.product_name_snapshot[:100]} — "
                    f"{item.quantity} {item.uom_code_snapshot}"
                )
            return BotReply(
                "\n".join(details)[:4096],
                (
                    (InlineAction(
                        "📍 وضعیت تحویل", f"ux:order:track:{order.id}",
                    ),),
                    (InlineAction("📦 سفارش‌های من", "shop:orders"),),
                ),
            )

        # Customer, support and notifications are separate domain modules.
        # Late imports avoid circular business dependencies and keep the
        # shared dispatcher stable as each Beta feature is added.
        from services.shop_customer_account import CustomerAccountFlow
        account = await CustomerAccountFlow(
            bot_context=context,
        ).reply(event, db)
        if account is not None:
            return account
        from services.shop_customer_support import CustomerSupportFlow
        support = await CustomerSupportFlow(
            bot_context=context,
        ).reply(event, db)
        if support is not None:
            return support

        if action.startswith("ux:"):
            return BotReply(
                "این گزینه برای بات فعلی در دسترس نیست.",
                ((InlineAction("🏠 منوی اصلی", "shop:home"),),),
            )

        if text and not text.startswith("/"):
            return await search.text_search(db, context, event)
        return None
