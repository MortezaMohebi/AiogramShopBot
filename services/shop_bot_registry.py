"""Transactional Store/Bot Registry operations without provider network calls.

New bots are always draft with no live dispatcher or payment permissions.
The current two bots are adopted under immutable legacy IDs; neither the
existing settings nor financial records are altered by this service.
"""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.shop_multibot import (
    DEFAULT_STORE_ID,
    ShopBot,
    ShopBotRegistryEvent,
    ShopStore,
)
from services import shop_admin_security as security
from services.shop_bot_secrets import credential_status

_SLUG = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_ALLOWED_PLATFORMS = frozenset({"telegram", "bale"})


def _safe_slug(value: str) -> str:
    """Validate canonical shop/bot identifiers without silently rewriting."""
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise security.SecurityRejected("invalid_registry_slug", 422)
    return value


def _safe_name(value: str) -> str:
    """Require a short visible label; never accept control characters."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value.strip()) <= 160
        or any(ord(character) < 32 for character in value)
    ):
        raise security.SecurityRejected("invalid_registry_name", 422)
    return value.strip()


def create_store(
    db: Session, *, slug: str, name: str, actor_id: int,
) -> ShopStore:
    """Register a second inactive store without exposing global catalog data."""
    slug = _safe_slug(slug)
    name = _safe_name(name)
    existing = db.scalar(select(ShopStore.id).where(ShopStore.slug == slug))
    if existing:
        raise security.SecurityRejected("store_slug_exists", 409)
    # Additional stores are not live until the later per-store catalog phase.
    store = ShopStore(
        id=str(uuid4()), slug=slug, name=name, state="paused",
    )
    db.add(store)
    security.audit(db, actor_id, "store.created", store.id)
    db.flush()
    return store


def register_bot(
    db: Session, *, store_id: str, platform: str,
    slug: str, name: str, actor_id: int,
) -> ShopBot:
    """Create an inert draft bot with no default access to any product."""
    if platform not in _ALLOWED_PLATFORMS:
        raise security.SecurityRejected("invalid_bot_platform", 422)
    slug = _safe_slug(slug)
    name = _safe_name(name)
    store = db.get(ShopStore, store_id)
    if store is None or store.state == "archived":
        raise security.SecurityRejected("store_not_found", 404)
    existing = db.scalar(select(ShopBot.id).where(
        ShopBot.store_id == store_id,
        ShopBot.slug == slug,
    ))
    if existing:
        raise security.SecurityRejected("bot_slug_exists", 409)
    bot = ShopBot(
        id=str(uuid4()), store_id=store.id,
        platform=platform, slug=slug, name=name,
        status="draft", runtime_owner="registry",
        version=1, credential_version=None,
    )
    db.add(bot)
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot.id, actor_id=actor_id,
        action="bot_drafted",
    ))
    db.flush()
    return bot


def serialize_store(store: ShopStore) -> dict:
    """Return non-sensitive store metadata."""
    return {
        "id": store.id,
        "slug": store.slug,
        "name": store.name,
        "state": store.state,
    }


def serialize_bot(db: Session, bot: ShopBot) -> dict:
    """Return redacted registration state, never Token or secret material."""
    return {
        "id": bot.id,
        "store_id": bot.store_id,
        "slug": bot.slug,
        "name": bot.name,
        "platform": bot.platform,
        "provider_bot_id": (
            str(bot.provider_bot_id) if bot.provider_bot_id else None
        ),
        "provider_username": bot.provider_username,
        "status": bot.status,
        "runtime_owner": bot.runtime_owner,
        "version": bot.version,
        "credential_version": bot.credential_version,
        "credentials": credential_status(db, bot_id=bot.id),
        "verified_at": (
            bot.verified_at.isoformat() if bot.verified_at else None
        ),
    }


def registry_snapshot(db: Session, *, store_id: str | None = None) -> dict:
    """Bound read-only registry snapshot for the trusted superadmin UI."""
    store_stmt = select(ShopStore).order_by(ShopStore.slug).limit(100)
    bot_stmt = select(ShopBot).order_by(
        ShopBot.store_id, ShopBot.slug,
    ).limit(300)
    if store_id is not None:
        store_stmt = store_stmt.where(ShopStore.id == store_id)
        bot_stmt = bot_stmt.where(ShopBot.store_id == store_id)
    stores = db.scalars(store_stmt).all()
    bots = db.scalars(bot_stmt).all()
    return {
        "stores": [serialize_store(store) for store in stores],
        "bots": [serialize_bot(db, bot) for bot in bots],
        "default_store_id": DEFAULT_STORE_ID,
        "runtime_migration_complete": False,
    }
