"""Safe per-bot receiver staging, provider verification and activation.

No webhook/getUpdates state changes until the provider identity and existing
webhook owner have been verified. Network mutations are never retried after
an ambiguous timeout; such records become needs_review for human recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models.shop_bot_operations import ShopBotOperations
from models.shop_multibot import (
    DEFAULT_STORE_ID, ShopBot, ShopBotCredential, ShopBotRegistryEvent,
)
from models.shop_multibot_receiver import (
    ShopBotReceiver, ShopBotReceiverEvent,
)
from services import shop_admin_security as security
from services.shop_bot_secrets import (
    decrypt_for_bot, decrypt_receiver_secret, encrypt_receiver_secret,
)
from services.shop_multibot_client import provider_client
from services.shop_multibot_webhook import webhook_url


def _event(
    db: AsyncSession, bot_id: str, actor_id: int | None,
    action: str, error_code: str | None = None,
) -> None:
    """Append an audit receipt without bot token or webhook secret."""
    db.add(ShopBotReceiverEvent(
        id=str(uuid4()), bot_id=bot_id, actor_id=actor_id,
        action=action, error_code=error_code,
    ))


async def stage_receiver(
    db: AsyncSession, *, bot_id: str, mode: str, actor_id: int,
) -> dict:
    """Register one receiver configuration; do not call Telegram/Bale."""
    if mode not in {"webhook", "polling"}:
        raise security.SecurityRejected("invalid_receiver_mode", 422)
    bot = await db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    if (
        bot is None or bot.store_id != DEFAULT_STORE_ID
        or bot.runtime_owner != "registry" or bot.status != "draft"
        or bot.provider_bot_id is None or bot.verified_at is None
    ):
        raise security.SecurityRejected("bot_runtime_not_ready", 409)
    credential = await db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot_id,
        ShopBotCredential.state == "staged",
        ShopBotCredential.verified_bot_id == bot.provider_bot_id,
    ).order_by(ShopBotCredential.version.desc()).limit(1))
    if (
        credential is None or credential.verified_at is None
        or not credential.ciphertext
    ):
        raise security.SecurityRejected("bot_credential_not_verified", 409)
    row = await db.scalar(select(ShopBotReceiver).where(
        ShopBotReceiver.bot_id == bot_id,
    ).with_for_update())
    if row is not None and row.state not in {"staged"}:
        raise security.SecurityRejected("receiver_change_in_progress", 409)
    secret = secrets.token_urlsafe(32)
    if row is None:
        row = ShopBotReceiver(
            bot_id=bot_id, binding_id=str(uuid4()),
            state="staged", version=1,
        )
        db.add(row)
    else:
        row.version += 1
    row.mode = mode
    row.credential_version = credential.version
    row.webhook_secret_ciphertext = encrypt_receiver_secret(bot_id, secret)
    row.webhook_secret_digest = hashlib.sha256(
        secret.encode("ascii")
    ).hexdigest()
    row.updated_by = actor_id
    row.last_error_code = None
    bot.version += 1
    _event(db, bot_id, actor_id, "staged")
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "bots.receiver_staged", bot_id,
    ))
    await db.commit()
    return {
        "ok": True, "bot_id": bot_id,
        "mode": mode, "state": "staged",
        "version": row.version,
    }


async def receiver_snapshot(db: AsyncSession, bot_id: str) -> dict:
    """Return non-secret receiver state to a signed administrator."""
    row = await db.get(ShopBotReceiver, bot_id)
    if row is None:
        return {
            "configured": False, "state": "disabled",
            "mode": None, "version": None,
            "credential_version": None,
            "next_update_id": None,
            "last_received_at": None,
            "last_error_code": None,
        }
    return {
        "configured": True, "state": row.state,
        "mode": row.mode, "version": row.version,
        "credential_version": row.credential_version,
        "next_update_id": row.next_update_id,
        "last_received_at": (
            row.last_received_at.isoformat() if row.last_received_at else None
        ),
        "last_error_code": row.last_error_code,
        # Binding URLs and secrets are not returned, even to superadmin.
    }


async def _guard_existing_provider_webhook(
    client, *, platform: str, target: str, mode: str,
) -> None:
    """Never adopt or delete an external endpoint owned by someone else."""
    if platform == "telegram":
        info = await asyncio.wait_for(client.get_webhook_info(), 12)
        actual = info.url
    else:
        info = await asyncio.wait_for(
            client._call("getWebhookInfo", {}), 12,
        )
        actual = info.get("url") if isinstance(info, dict) else None
        if not isinstance(actual, str):
            raise security.SecurityRejected("provider_state_unavailable", 503)
    if actual and actual != target:
        raise security.SecurityRejected("webhook_owned_elsewhere", 409)
    if mode == "polling" and actual:
        raise security.SecurityRejected("webhook_owned_elsewhere", 409)


async def _apply_provider(
    client, *, platform: str, mode: str, url: str, secret: str,
) -> None:
    """Register exactly one webhook, or validate an already empty poll route."""
    await _guard_existing_provider_webhook(
        client, platform=platform, target=url, mode=mode,
    )
    if mode == "polling":
        return
    if platform == "telegram":
        await asyncio.wait_for(client.set_webhook(
            url=url,
            secret_token=secret,
            drop_pending_updates=False,
            allowed_updates=[
                "message", "callback_query", "pre_checkout_query",
            ],
            max_connections=2,
        ), 15)
    else:
        await asyncio.wait_for(client._call(
            "setWebhook", {"url": url},
        ), 15)
    await _guard_existing_provider_webhook(
        client, platform=platform, target=url, mode=mode,
    )


async def _mark_needs_review(
    bot_id: str, actor_id: int, code: str,
) -> None:
    """Store an ambiguous activation even if the incoming request was lost."""
    from db import session_maker

    async with session_maker() as db:
        row = await db.get(ShopBotReceiver, bot_id, with_for_update=True)
        if row is not None and row.state == "applying":
            row.state = "needs_review"
            row.last_error_code = code
            _event(db, bot_id, actor_id, "needs_review", code)
            await db.commit()


async def activate_receiver(
    db: AsyncSession, *, bot_id: str, actor_id: int,
    expected_version: int, supervisor,
) -> dict:
    """Activate one verified draft without taking over unrelated webhooks."""
    if supervisor is None or not supervisor.owns_lease:
        raise security.SecurityRejected("receiver_worker_unavailable", 503)
    if not getattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", False):
        raise security.SecurityRejected("multibot_runtime_disabled", 409)
    # A cached boolean is insufficient after PostgreSQL lease loss.
    await supervisor.check_lease()

    bot = await db.scalar(select(ShopBot).where(
        ShopBot.id == bot_id,
    ).with_for_update())
    row = await db.scalar(select(ShopBotReceiver).where(
        ShopBotReceiver.bot_id == bot_id,
    ).with_for_update())
    if bot is None or row is None or row.version != expected_version:
        raise security.SecurityRejected("configuration_changed", 409)
    if (
        bot.runtime_owner != "registry" or bot.status != "draft"
        or row.state != "staged" or bot.provider_bot_id is None
    ):
        raise security.SecurityRejected("invalid_operation_state", 409)
    credential = await db.scalar(select(ShopBotCredential).where(
        ShopBotCredential.bot_id == bot_id,
        ShopBotCredential.version == row.credential_version,
        ShopBotCredential.state == "staged",
    ).with_for_update())
    if (
        credential is None or credential.verified_bot_id != bot.provider_bot_id
        or credential.verified_at is None or not credential.ciphertext
    ):
        raise security.SecurityRejected("bot_credential_not_verified", 409)

    token = decrypt_for_bot(
        bot.id, bot.platform, credential.ciphertext,
    )
    secret = decrypt_receiver_secret(bot.id, row.webhook_secret_ciphertext)
    url = webhook_url(row.binding_id, secret)
    if row.mode == "webhook" and not url:
        raise security.SecurityRejected("webhook_url_invalid", 422)

    row.state = "applying"
    row.updated_by = actor_id
    _event(db, bot_id, actor_id, "applying")
    await db.commit()

    # All requests to the provider are outside the database transaction;
    # a crash or timeout never results in an automatic replay of setWebhook.
    try:
        async with provider_client(
            bot.platform, token, bot_id=bot.id,
        ) as client:
            if bot.platform == "telegram":
                identity = await asyncio.wait_for(client.get_me(), 12)
                actual_id = identity.id
            else:
                identity = await asyncio.wait_for(
                    client._call("getMe", {}), 12,
                )
                actual_id = identity.get("id")
            if actual_id != bot.provider_bot_id:
                raise security.SecurityRejected("bot_identity_mismatch", 409)
            await _apply_provider(
                client, platform=bot.platform,
                mode=row.mode, url=url, secret=secret,
            )
            await supervisor.check_lease()
    except BaseException as error:
        code = (
            error.code if isinstance(error, security.SecurityRejected)
            else "provider_outcome_unknown"
        )
        try:
            await _mark_needs_review(bot_id, actor_id, code)
        except Exception:
            # A remaining applying row is quarantined on restart.
            pass
        if isinstance(error, asyncio.CancelledError):
            raise
        raise security.SecurityRejected(
            "receiver_needs_review", 503,
        ) from None

    # Reopen a fresh transaction after provider verification and preserve
    # original revision expectations before enabling any normal customer flow.
    row = await db.get(
        ShopBotReceiver, bot_id, with_for_update=True,
    )
    bot = await db.get(ShopBot, bot_id, with_for_update=True)
    credential = await db.get(
        ShopBotCredential, credential.id, with_for_update=True,
    )
    if (
        row.state != "applying"
        or bot.status != "draft"
        or credential.state != "staged"
        or credential.verified_bot_id != bot.provider_bot_id
    ):
        await db.rollback()
        await _mark_needs_review(
            bot_id, actor_id, "configuration_changed",
        )
        raise security.SecurityRejected("receiver_needs_review", 503)

    credential.state = "active"
    credential.activated_at = datetime.now(timezone.utc)
    bot.credential_version = credential.version
    bot.status = "active"
    bot.version += 1
    row.state = "active"
    row.version += 1
    row.last_error_code = None
    ops = await db.get(ShopBotOperations, bot_id, with_for_update=True)
    if ops is None:
        ops = ShopBotOperations(bot_id=bot_id)
        db.add(ops)
    ops.desired_state = "active"
    ops.updated_by = actor_id
    db.add(ShopBotRegistryEvent(
        id=str(uuid4()), bot_id=bot_id, actor_id=actor_id,
        action="bot_updated", credential_version=credential.version,
    ))
    _event(db, bot_id, actor_id, "activated")
    await db.run_sync(lambda sync: security.audit(
        sync, actor_id, "bots.receiver_activated", bot_id,
    ))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await _mark_needs_review(
            bot_id, actor_id, "activation_persist_failed",
        )
        raise security.SecurityRejected(
            "receiver_needs_review", 503,
        ) from None
    # Incoming webhook traffic is allowed immediately after DB commit.
    # Only polling requires starting a local owned worker.
    if row.mode == "polling":
        await supervisor.start_polling(bot_id)
    return {
        "ok": True, "bot_id": bot_id, "state": "active",
        "mode": row.mode, "credential_version": credential.version,
    }
