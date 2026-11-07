"""One verified, declarative customer Home menu across Telegram and Bale.

Store and Bot policies only select known action IDs. Visibility is separately
checked against capabilities, so a custom menu cannot grant access to a
disabled Cart, forbidden Product, unknown Provider or another Store.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import InlineAction, Platform
from models.shop_customer_navigation import ShopBotMenuPolicy, ShopStoreMenuPolicy
from models.shop_multibot import ShopBot
from services import shop_admin_security as security
from services.shop_channel_features import get_features

DEFAULT_MENU = ("shop", "search", "cart", "orders", "account", "support")
MENU_LABELS = {
    "shop": "🛍 فروشگاه",
    "search": "🔎 جستجوی محصول",
    "cart": "🛒 سبد خرید",
    "orders": "📦 سفارش‌های من",
    "account": "👤 حساب من",
    "support": "🆘 پشتیبانی",
}
MENU_CALLBACKS = {
    "shop": "shop:list:0",
    "search": "ux:search",
    "cart": "shop:cart",
    "orders": "shop:orders",
    "account": "ux:account",
    "support": "ux:support",
}


def normalize_menu(values: Sequence[str]) -> tuple[str, ...]:
    """Allow only nonempty, nonduplicated, stable action identifiers."""
    if (
        isinstance(values, (str, bytes))
        or not isinstance(values, (list, tuple))
        or len(values) == 0 or len(values) > len(DEFAULT_MENU)
        or any(not isinstance(item, str) for item in values)
        or any(item not in MENU_LABELS for item in values)
        or len(set(values)) != len(values)
        or "shop" not in values
    ):
        raise ValueError("Invalid menu actions.")
    return tuple(values)


def read_menu(value: str | None) -> tuple[str, ...]:
    """Reject corrupt policy JSON rather than widening the menu."""
    if value is None:
        return DEFAULT_MENU
    try:
        loaded = json.loads(value)
        return normalize_menu(loaded)
    except (ValueError, TypeError):
        raise security.SecurityRejected("invalid_menu_policy", 409) from None


def menu_rows(
    actions: Sequence[str], *, platform: Platform, cart_enabled: bool,
) -> tuple[tuple[InlineAction, ...], ...]:
    """Render platform-neutral inline buttons with under-64-byte callbacks."""
    if platform not in {Platform.TELEGRAM, Platform.BALE}:
        raise ValueError("Unknown bot platform.")
    requested = normalize_menu(actions)
    return tuple(
        (InlineAction(MENU_LABELS[action], MENU_CALLBACKS[action]),)
        for action in requested
        if action != "cart" or cart_enabled
    )


async def effective_menu(
    db: AsyncSession, *, bot_id: str, platform: Platform,
) -> tuple[tuple[InlineAction, ...], ...]:
    """Load verified Store and Bot layout without trusting a callback bot ID."""
    bot = await db.get(ShopBot, bot_id)
    if bot is None or bot.platform != platform.value:
        raise security.SecurityRejected("bot_identity_mismatch", 403)
    store_policy = await db.get(ShopStoreMenuPolicy, bot.store_id)
    bot_policy = await db.get(ShopBotMenuPolicy, bot_id)
    if bot_policy is not None and bot_policy.store_id != bot.store_id:
        raise security.SecurityRejected("menu_store_mismatch", 409)
    configured = (
        bot_policy.actions_json if bot_policy is not None
        else store_policy.actions_json if store_policy is not None
        else None
    )
    features = await get_features(db, platform.value, bot_id=bot_id)
    return menu_rows(
        read_menu(configured), platform=platform,
        cart_enabled=features.cart_enabled,
    )


async def menu_snapshot(
    db: AsyncSession, *, bot_id: str | None = None,
    store_id: str | None = None,
) -> dict:
    """Serialize editable policy fields; never include private bot tokens."""
    if (bot_id is None) == (store_id is None):
        raise security.SecurityRejected("invalid_menu_policy", 422)
    bot = await db.get(ShopBot, bot_id) if bot_id else None
    if bot_id is not None and bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    owner = bot.store_id if bot else cast(str, store_id)
    row = (
        await db.get(ShopBotMenuPolicy, bot_id)
        if bot else await db.get(ShopStoreMenuPolicy, owner)
    )
    fallback = await db.get(ShopStoreMenuPolicy, owner) if bot else None
    raw = (
        row.actions_json if row is not None
        else fallback.actions_json if fallback is not None
        else None
    )
    return {
        "scope": "bot" if bot else "store",
        "store_id": owner,
        "bot_id": bot_id,
        "version": row.version if row else 0,
        "inherited": bot is not None and row is None,
        "actions": list(read_menu(raw)),
        "available_actions": [
            {"key": key, "label": MENU_LABELS[key], "callback": MENU_CALLBACKS[key]}
            for key in DEFAULT_MENU
        ],
    }


async def set_menu(
    db: AsyncSession, *, actions: list[str], actor_id: int,
    expected_version: int, bot_id: str | None = None,
    store_id: str | None = None,
) -> dict:
    """Update one Store/Bot's display policy using optimistic concurrency."""
    try:
        chosen = normalize_menu(actions)
    except ValueError:
        raise security.SecurityRejected("invalid_menu_policy", 422) from None
    if (bot_id is None) == (store_id is None):
        raise security.SecurityRejected("invalid_menu_policy", 422)
    bot = await db.get(ShopBot, bot_id) if bot_id else None
    if bot_id is not None and bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    owner = bot.store_id if bot else cast(str, store_id)
    cls = ShopBotMenuPolicy if bot else ShopStoreMenuPolicy
    pk = cast(str, bot_id or store_id)
    row = await db.scalar(
        select(cls).where(
            cls.bot_id == pk if bot else cls.store_id == pk,
        ).with_for_update()
    )
    if row is None:
        if expected_version != 0:
            raise security.SecurityRejected("configuration_changed", 409)
        row = (
            ShopBotMenuPolicy(bot_id=pk, store_id=owner)
            if bot else ShopStoreMenuPolicy(store_id=owner)
        )
        db.add(row)
    elif row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    row.actions_json = json.dumps(list(chosen), ensure_ascii=False)
    row.version = row.version + 1 if expected_version else 1
    row.updated_by = actor_id
    await db.commit()
    return await menu_snapshot(
        db, bot_id=bot_id, store_id=store_id,
    )
