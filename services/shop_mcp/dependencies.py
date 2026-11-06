"""Fingerprint reviewed native dependencies without exposing private assets."""

from __future__ import annotations

import hashlib
from dataclasses import asdict

from sqlalchemy import select

from models.shop_bot_operations import ShopBotOperations
from models.shop_channel_features import ShopChannelFeature
from models.shop_content import Product, ProductMedia
from models.shop_multibot import ShopBot
from models.shop_store_commerce import ShopBotCommercePolicy
from services.shop_actions.definitions import definition as action_definition
from services.shop_channel_features import PLATFORMS, get_features
from services.shop_mcp.contracts import McpRejected
from services.shop_workflow_schema import canonical_json


def digest(value) -> str:
    """Hash native canonical bytes with exact Unicode and numeric types."""
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


async def snapshot(db, *, store_id, definition, bindings=()) -> dict:
    """Bind Bot policy, typed contracts and referenced media identity."""
    bot_ids = {item["bot_id"] for item in bindings}
    if definition.assignment.mode == "selected":
        bot_ids.update(definition.assignment.bot_ids)
    bots = (
        await db.scalars(
            select(ShopBot)
            .where(
                ShopBot.store_id == store_id,
                ShopBot.id.in_(bot_ids),
            )
            .order_by(ShopBot.id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    if {bot.id for bot in bots} != bot_ids:
        raise McpRejected("mcp_dependency_changed", 409)
    # Match the updater's platform order, independent of Bot UUID order.
    # Refresh identities as well as taking compatible policy SHARE locks.
    for platform in PLATFORMS:
        if platform in {bot.platform for bot in bots}:
            await db.scalar(
                select(ShopChannelFeature)
                .where(
                    ShopChannelFeature.platform == platform,
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
    bot_states = []
    for bot in bots:
        await db.scalar(
            select(ShopBotCommercePolicy)
            .where(
                ShopBotCommercePolicy.bot_id == bot.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        operations = await db.scalar(
            select(ShopBotOperations)
            .where(
                ShopBotOperations.bot_id == bot.id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        bot_states.append(
            {
                "id": bot.id,
                "platform": bot.platform,
                "version": bot.version,
                "status": bot.status,
                "runtime_owner": bot.runtime_owner,
                "credential_version": bot.credential_version,
                "desired_state": operations.desired_state
                if operations
                else None,
                "features": asdict(
                    await get_features(db, bot.platform, bot_id=bot.id)
                ),
            }
        )
    contracts, media_ids = {}, set()
    for node in definition.nodes:
        if node.type == "action":
            key, version = (
                node.config["action_key"],
                node.config["action_version"],
            )
            action = action_definition(key, version)
            contracts[key + "@" + version] = (
                digest(action.descriptor.model_dump(mode="json"))
                if action is not None
                else "unavailable"
            )
        for platform in definition.target_platforms:
            config = node.config | node.platform_overrides.get(platform, {})
            if config.get("media_id") is not None:
                media_ids.add(config["media_id"])
            media_ids.update(config.get("media_ids", []))
    rows = (
        await db.scalars(
            select(ProductMedia)
            .join(Product)
            .where(
                Product.store_id == store_id,
                ProductMedia.id.in_(media_ids),
            )
            .order_by(ProductMedia.id)
            .with_for_update(read=True, of=ProductMedia)
            .execution_options(populate_existing=True)
        )
    ).all()
    if {row.id for row in rows} != media_ids:
        raise McpRejected("mcp_dependency_changed", 409)
    return {
        "bots": bot_states,
        "action_contracts": contracts,
        "media": [
            {
                "id": row.id,
                "fingerprint": digest(
                    {
                        # Keep storage identity inside native trust.
                        "storage_key": row.storage_key,
                        "kind": row.kind,
                        "product_id": row.product_id,
                        "size_bytes": row.size_bytes,
                        "mime_type": row.mime_type,
                        "published": row.is_published,
                        "caption": row.caption,
                    }
                ),
            }
            for row in rows
        ],
    }
