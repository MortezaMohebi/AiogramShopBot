"""Prove bot ownership using provider getMe without activating any receiver.

A verification uses only the bot-specific staged secret or the already-bound
legacy deployment credential. It never registers webhooks, sends messages,
fetches updates, starts polling, or returns a token to the dashboard.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_bot_profile import ShopBotProfile
from models.shop_multibot import (
    ShopBot,
    ShopBotCredential,
    ShopBotRegistryEvent,
)
from services import shop_admin_security as security
from services import shop_bot_secrets as vault


@dataclass(frozen=True, slots=True)
class ProviderBotIdentity:
    """Provider-confirmed non-secret bot ID and public username."""

    bot_id: int
    username: str | None


async def provider_get_me(
    platform: str, token: str,
) -> ProviderBotIdentity:
    """Query a provider once, with a hard timeout and no message side effects."""
    if platform == "telegram":
        from utils.telegram import create_bot, create_telegram_session

        session = create_telegram_session()
        try:
            bot = create_bot(token, session)
            identity = await asyncio.wait_for(bot.get_me(), timeout=12)
            return ProviderBotIdentity(identity.id, identity.username)
        finally:
            await session.close()

    if platform == "bale":
        from aiohttp import ClientSession, ClientTimeout
        from channels.bale import BaleTransport

        async with ClientSession(
            timeout=ClientTimeout(total=12), trust_env=False,
        ) as http:
            response = await asyncio.wait_for(
                BaleTransport(token, http)._call("getMe", {}),
                timeout=12,
            )
        if not isinstance(response, dict):
            raise ValueError("Invalid provider response")
        return ProviderBotIdentity(
            response.get("id"), response.get("username"),
        )

    raise security.SecurityRejected("invalid_bot_platform", 422)


def _get_token(db, bot: ShopBot, credential: ShopBotCredential) -> str:
    """Resolve the exact selected version, never an arbitrary client secret."""
    if bot.runtime_owner == "legacy":
        if (
            bot.status != "legacy"
            or credential.source != "environment"
            or credential.state != "active"
            or credential.version != bot.credential_version
        ):
            raise security.SecurityRejected("invalid_credential_state", 409)
        return vault.resolve_active_token(db, bot_id=bot.id)
    if (
        bot.status != "draft" or credential.source != "encrypted"
        or credential.state != "staged" or not credential.ciphertext
    ):
        raise security.SecurityRejected("invalid_credential_state", 409)
    return vault.decrypt_for_bot(
        bot.id, bot.platform, credential.ciphertext,
    )


async def verify_bot(
    db: AsyncSession, *, bot_id: str, actor_id: int,
    version: int | None = None,
    probe: Callable[[str, str], Awaitable[ProviderBotIdentity]] | None = None,
) -> dict:
    """Verify getMe then conditionally save identity and credential receipt.

    Token resolution and a bounded network request happen outside row locks.
    After getMe, optimistic checks reject any newer credential or bot update.
    A duplicate provider identity across two registry bots is prohibited.
    """
    bot = await db.get(ShopBot, bot_id)
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)

    credential_version = (
        version if version is not None else bot.credential_version
    )
    if credential_version is None or credential_version < 1:
        raise security.SecurityRejected("bot_credential_missing", 409)
    selected = await db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot.id,
        ShopBotCredential.version == credential_version,
    ))
    if selected is None:
        raise security.SecurityRejected("invalid_credential_state", 409)
    if bot.runtime_owner != "legacy":
        latest = await db.scalar(select(ShopBotCredential.version).where(
            ShopBotCredential.bot_id == bot.id,
            ShopBotCredential.state == "staged",
        ).order_by(ShopBotCredential.version.desc()).limit(1))
        if latest != credential_version:
            raise security.SecurityRejected("invalid_credential_state", 409)

    token = await db.run_sync(
        lambda sync: _get_token(sync, bot, selected)
    )
    observed_version = bot.version
    observed_state = selected.state
    try:
        identity = await (
            probe or provider_get_me
        )(bot.platform, token)
    except security.SecurityRejected:
        raise
    except Exception:
        # Never expose provider exceptions that can include token-bearing URLs.
        raise security.SecurityRejected(
            "provider_state_unavailable", 503,
        ) from None
    finally:
        # The token is never logged or returned; the local value expires
        # when this request exits.
        token = None

    if (
        type(identity.bot_id) is not int or identity.bot_id <= 0
        or identity.username is not None and (
            not isinstance(identity.username, str)
            or len(identity.username) > 255
        )
    ):
        raise security.SecurityRejected("provider_state_unavailable", 503)

    locked = await db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    latest_credential = await db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.id == selected.id,
    ).with_for_update().execution_options(populate_existing=True))
    if (
        locked is None
        or locked.version != observed_version
        or latest_credential is None
        or latest_credential.state != observed_state
        or latest_credential.version != credential_version
    ):
        raise security.SecurityRejected("configuration_changed", 409)
    if locked.runtime_owner != "legacy" and (
        latest_credential.state != "staged" or locked.status != "draft"
    ):
        raise security.SecurityRejected("invalid_credential_state", 409)
    if locked.provider_bot_id is not None and (
        locked.provider_bot_id != identity.bot_id
    ):
        raise security.SecurityRejected("bot_identity_mismatch", 409)
    conflict = await db.scalar(select(ShopBot.id).where(
        ShopBot.platform == locked.platform,
        ShopBot.provider_bot_id == identity.bot_id,
        ShopBot.id != locked.id,
    ).limit(1))
    if conflict is not None:
        raise security.SecurityRejected("duplicate_provider_bot", 409)

    if locked.runtime_owner == "legacy":
        # Preserve the metadata consumed by the original dual-bot dashboard.
        profile = await db.scalar(select(ShopBotProfile).where(
            ShopBotProfile.platform == locked.platform,
        ).with_for_update())
        if profile is not None:
            if profile.provider_bot_id is not None and (
                profile.provider_bot_id != identity.bot_id
            ):
                raise security.SecurityRejected("bot_identity_mismatch", 409)
            profile.provider_bot_id = identity.bot_id
            profile.provider_username = identity.username
            profile.verified_at = security.clock()

    locked.provider_bot_id = identity.bot_id
    locked.provider_username = identity.username
    locked.verified_at = security.clock()
    locked.version += 1
    latest_credential.verified_bot_id = identity.bot_id
    latest_credential.verified_username = identity.username
    latest_credential.verified_at = security.clock()
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=locked.id,
        actor_id=actor_id, action="bot_updated",
        credential_version=credential_version,
    ))
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "bots.identity_verified", locked.id,
    ))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("duplicate_provider_bot", 409) from None
    return {
        "ok": True, "bot_id": locked.id,
        "provider_bot_id": str(identity.bot_id),
        "provider_username": identity.username,
        "credential_version": credential_version,
        "verified_at": locked.verified_at.isoformat(),
        "runtime_activated": False,
    }
