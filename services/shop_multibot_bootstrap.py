"""Idempotent Codespaces-only adoption of original Telegram and Bale bots.

Called within the bootstrap DDL transaction and its PostgreSQL advisory lock.
The original bot profile, connection, cart, order, wallet, and invoice tables
are never updated. Existing Registry records are not overwritten on reruns.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from models.shop_bot_profile import ShopBotProfile
from models.shop_content import ShopSettings
from models.shop_multibot import (
    DEFAULT_STORE_ID,
    ENV_TOKEN_KEYS,
    LEGACY_BOT_IDS,
    ShopBot,
    ShopBotCredential,
    ShopBotRegistryEvent,
    ShopStore,
)


async def adopt_legacy_codespace(connection: AsyncConnection) -> None:
    """Adopt legacy metadata under the existing bootstrap transaction."""
    await connection.run_sync(_adopt_synchronous)


def _adopt_synchronous(connection) -> None:
    """Use PostgreSQL ON CONFLICT for safe repeated bootstrap invocations."""
    existing_settings = connection.execute(
        select(ShopSettings.__table__).where(ShopSettings.id == 1)
    ).mappings().first()
    brand = (
        (existing_settings.get("brand_name") or "").strip()
        if existing_settings else ""
    ) or "فروشگاه اصلی"

    connection.execute(pg_insert(ShopStore.__table__).values(
        id=DEFAULT_STORE_ID,
        slug="default", name=brand[:160], state="active",
    ).on_conflict_do_nothing(index_elements=["id"]))

    store_exists = connection.scalar(select(ShopStore.id).where(
        ShopStore.id == DEFAULT_STORE_ID,
    ))
    if store_exists is None:
        raise RuntimeError("Default store registry entry was not created")
    store_slug = connection.scalar(select(ShopStore.slug).where(
        ShopStore.id == DEFAULT_STORE_ID,
    ))
    if store_slug != "default":
        raise RuntimeError("Default store registry identity is inconsistent")

    records = connection.execute(select(ShopBotProfile.__table__)).mappings()
    profiles = {row["platform"]: row for row in records}

    for platform, bot_id in LEGACY_BOT_IDS.items():
        existing_bot = connection.execute(select(ShopBot.__table__).where(
            ShopBot.id == bot_id,
        )).mappings().first()
        if existing_bot and (
            existing_bot["platform"] != platform
            or existing_bot["store_id"] != DEFAULT_STORE_ID
            or existing_bot["runtime_owner"] != "legacy"
            or existing_bot["status"] != "legacy"
        ):
            raise RuntimeError(
                "Legacy bot registry identity conflicts with an existing bot"
            )
        profile = profiles.get(platform, {})
        inserted = connection.execute(
            pg_insert(ShopBot.__table__).values(
                id=bot_id, store_id=DEFAULT_STORE_ID,
                slug=f"legacy-{platform}",
                name=str(
                    profile.get("display_name") or f"Legacy {platform} Bot"
                )[:160],
                platform=platform,
                provider_bot_id=profile.get("provider_bot_id"),
                provider_username=profile.get("provider_username"),
                status="legacy",
                runtime_owner="legacy",
                credential_version=1,
                version=1,
                verified_at=profile.get("verified_at"),
            ).on_conflict_do_nothing(index_elements=["id"])
            .returning(ShopBot.id)
        )
        added = inserted.scalar_one_or_none() is not None

        connection.execute(
            pg_insert(ShopBotCredential.__table__).values(
                id=str(uuid4()), bot_id=bot_id, version=1,
                source="environment", state="active",
                environment_key=ENV_TOKEN_KEYS[platform],
            ).on_conflict_do_nothing(
                index_elements=["bot_id", "version"],
            )
        )
        if added:
            connection.execute(pg_insert(ShopBotRegistryEvent.__table__).values(
                id=str(uuid4()), bot_id=bot_id,
                actor_id=None, action="legacy_adopted",
                credential_version=1,
            ))
