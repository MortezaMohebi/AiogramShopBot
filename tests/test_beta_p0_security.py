"""P0 offline acceptance: tenant isolation and provider-update safety.

The policy must remain fail-closed for registered bots until a specific
product/category grant exists; matching numeric IDs are never a Store grant.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from models.shop_multibot import ShopBot, ShopStore
from services.shop_bot_catalog_acl import CatalogScope, permitted_product_clause, resolve_scope
from services.shop_relay_routing import SAFE_RELAY_FAILOVER


class CatalogDb:
    """In-memory domain owner lookup with the same async get signature."""

    def __init__(self, bot: ShopBot, store: ShopStore) -> None:
        """Keep the caller-provided identities distinct from request payloads."""
        self.bot = bot
        self.store = store

    async def get(self, model, key):
        """Return only matching authenticated model keys."""
        if model is ShopBot and key == self.bot.id:
            return self.bot
        if model is ShopStore and key == self.store.id:
            return self.store
        return None


def test_acl_query_always_filters_store_even_for_legacy() -> None:
    """Published products in a different Store are not visible via callbacks."""
    scope = CatalogScope(
        bot_id=str(uuid4()), store_id=str(uuid4()),
        default_allow=True, available=True,
    )
    compiled = str(
        select(1).where(permitted_product_clause(scope)).compile(
            dialect=postgresql.dialect(),
        )
    ).lower()
    assert "shop_products.store_id" in compiled


def test_registered_bot_in_nondefault_store_can_resolve_scope() -> None:
    """Multi-Store does not blacklist legitimate nondefault Store catalogs."""
    store_id = str(uuid4())
    bot = ShopBot(
        id=str(uuid4()), store_id=store_id,
        name="Registered", slug="registry", platform="telegram",
        status="active", runtime_owner="registry",
        credential_version=1,
    )
    store = ShopStore(id=store_id, slug="another", name="Another", state="active")
    scope = asyncio.run(resolve_scope(CatalogDb(bot, store), bot_id=bot.id))
    assert scope.available
    assert scope.store_id == store_id
    assert not scope.default_allow


def test_registered_bot_policy_respects_default_deny() -> None:
    """An active bot without any ACL grant does not inherit legacy products."""
    scope = CatalogScope(
        bot_id=str(uuid4()), store_id=str(uuid4()),
        default_allow=False, available=True,
    )
    compiled = str(
        select(1).where(permitted_product_clause(scope)).compile(
            dialect=postgresql.dialect(),
        )
    ).lower()
    assert "shop_bot_product_rules" in compiled or "shop_bot_category_rules" in compiled


def test_updates_must_never_use_uncertain_network_failover() -> None:
    """getUpdates(offset=...) acknowledges updates and is not read-only."""
    assert "getUpdates" not in SAFE_RELAY_FAILOVER
    assert "sendMessage" not in SAFE_RELAY_FAILOVER
    assert "sendInvoice" not in SAFE_RELAY_FAILOVER
    assert "refundStarPayment" not in SAFE_RELAY_FAILOVER
    assert {"getMe", "getWebhookInfo", "getFile"} <= SAFE_RELAY_FAILOVER
