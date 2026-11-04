"""Single Telegram/Bale semantic customer interaction router.

Both native messaging adapters pass the same InboundEvent and verified
BotContext here. This router owns UX callbacks and delegates commerce
actions to the existing Catalog/Cart/Order/Wallet domain services.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction, Platform
from models.shop_customer_navigation import ShopCustomerChatState
from services.shop_bot_context import BotContext, resolve_legacy_bot_context
from services import shop_customer_search as search


_SEARCH_PAGE = re.compile(r"ux:search:page:(0|[1-9][0-9]{0,3})\Z")
_SEARCH_FIELD = re.compile(r"ux:search:field:(all|name|sku|description)\Z")


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
