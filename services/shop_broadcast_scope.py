"""Resolve Registry broadcast permission without payment permission inheritance."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.sql import Select, SQLColumnExpression

from services.shop_service_controls import registry_broadcast_allowed
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    ShopBot,
    ShopBotCredential,
    ShopStore,
)
from models.shop_multibot_receiver import ShopBotReceiver


def registry_dispatch_enabled() -> bool:
    """Require an explicit deployment opt-in for Registry-owned campaigns."""
    return registry_broadcast_allowed()


def ready_registry_bot(
    *,
    bot_id: str | SQLColumnExpression[str],
    store_id: str | SQLColumnExpression[str],
) -> Select[tuple[ShopBot]]:
    """Build an exact-scope runtime gate usable in correlated claim queries.

    Marketing requires a live receiver so opt-outs remain available. Payment
    rails and settlement permissions never grant announcement permission.
    """
    return (
        select(ShopBot)
        .join(ShopStore, ShopStore.id == ShopBot.store_id)
        .join(ShopBotOperations, ShopBotOperations.bot_id == ShopBot.id)
        .join(ShopBotReceiver, ShopBotReceiver.bot_id == ShopBot.id)
        .join(ShopBotCredential, ShopBotCredential.bot_id == ShopBot.id)
        .where(
            ShopBot.id == bot_id,
            ShopBot.store_id == store_id,
            ShopStore.state == "active",
            ShopBot.runtime_owner == "registry",
            ShopBot.status == "active",
            ShopBot.provider_bot_id > 0,
            ShopBotOperations.desired_state == "active",
            ShopBotReceiver.state == "active",
            ShopBotReceiver.credential_version == ShopBot.credential_version,
            ShopBotCredential.version == ShopBot.credential_version,
            ShopBotCredential.state == "active",
            ShopBotCredential.source == "encrypted",
            ShopBotCredential.ciphertext.is_not(None),
            ShopBotCredential.verified_bot_id == ShopBot.provider_bot_id,
        )
    )
