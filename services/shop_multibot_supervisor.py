"""One bounded shared multi-bot receiver pool with durable per-bot offsets.

This does not launch a container per bot. A single PostgreSQL advisory lease
elects one owner; each polling bot is independently tracked and throttled.
Webhook routing is authenticated through DB-bound opaque path secrets.
Interrupted or ambiguous provider calls are quarantined, never blindly sent
a second time.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID

from sqlalchemy import select, text

import config
from channels.contracts import Platform
from db import engine, session_maker
from models.shop_multibot import ShopBot
from models.shop_multibot_receiver import ShopBotReceiver
from models.shop_delivery import ShopInboundUpdate
from services import shop_admin_security as security
from services.shop_bot_context import resolve_bot_context
from services.shop_bot_secrets import resolve_active_token
from services.shop_multibot_client import provider_client
from services.shop_multibot_dispatch import dispatch
from services.shop_runtime.ingress import try_ingress
from services.shop_updates import claim_update, finish_update

LOG = logging.getLogger(__name__)
_LEASE_ID = 90211025
MAX_POLLING_BOTS = 50


class MultiBotSupervisor:
    """Manage up to a deployment-bounded number of active independent bots."""

    def __init__(self, app) -> None:
        """Bind the legacy FastAPI application without changing its routes."""
        self.app = app
        self.lease = None
        self.lease_pid = None
        self.lease_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.polling: dict[str, asyncio.Task] = {}
        self.owns_lease = False

    async def start(self) -> None:
        """Acquire an exclusive DB lease and restore only confirmed receivers."""
        if not getattr(config, "MULTIBOT_V2_RUNTIME_ENABLED", False):
            LOG.info("Multi-bot v2 receiver is disabled by deployment policy")
            return
        self.lease = await engine.connect()
        acquired = await self.lease.scalar(text(
            "SELECT pg_try_advisory_lock(:identifier)"
        ), {"identifier": _LEASE_ID})
        await self.lease.commit()
        if not acquired:
            await self.lease.close()
            self.lease = None
            raise RuntimeError(
                "Another service owns the shared multi-bot receiver lease"
            )
        self.owns_lease = True
        self.lease_pid = await self.lease.scalar(
            text("SELECT pg_backend_pid()")
        )
        await self.lease.commit()
        async with session_maker() as db:
            incomplete = (await db.scalars(select(ShopBotReceiver).where(
                ShopBotReceiver.state == "applying",
            ).with_for_update())).all()
            for item in incomplete:
                item.state = "needs_review"
                item.last_error_code = "receiver_interrupted"
            await db.commit()
            bots = (await db.scalars(select(ShopBotReceiver.bot_id).where(
                ShopBotReceiver.mode == "polling",
                ShopBotReceiver.state == "active",
            ).limit(MAX_POLLING_BOTS + 1))).all()
            if len(bots) > MAX_POLLING_BOTS:
                raise RuntimeError("Too many active polling bots")
        self.app.state.multi_bot_supervisor = self
        for bot_id in bots:
            await self.start_polling(bot_id)

    async def check_lease(self) -> None:
        """Stop on DB connection loss; never allow concurrent receiver owners."""
        if not self.owns_lease:
            raise security.SecurityRejected(
                "receiver_worker_unavailable", 503,
            )
        async with self.lease_lock:
            try:
                if self.lease is None or self.lease.closed:
                    raise RuntimeError("Lease unavailable")
                observed = await asyncio.wait_for(self.lease.scalar(
                    text("SELECT pg_backend_pid()")
                ), 4)
                await self.lease.commit()
                if observed != self.lease_pid:
                    raise RuntimeError("Lease owner changed")
            except Exception:
                self.owns_lease = False
                self.stop_event.set()
                for task in self.polling.values():
                    task.cancel()
                raise security.SecurityRejected(
                    "receiver_lease_lost", 503,
                ) from None

    async def close(self) -> None:
        """Stop all polling jobs and close the shared database lease."""
        self.stop_event.set()
        tasks = list(self.polling.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.polling.clear()
        if self.lease is not None:
            try:
                if not self.lease.closed:
                    await self.lease.execute(text(
                        "SELECT pg_advisory_unlock(:identifier)"
                    ), {"identifier": _LEASE_ID})
                    await self.lease.commit()
            finally:
                await self.lease.close()
                self.lease = None
        self.owns_lease = False

    async def start_polling(self, bot_id: str) -> None:
        """Start at most one task per bot with a verified empty webhook state."""
        await self.check_lease()
        if bot_id in self.polling and not self.polling[bot_id].done():
            return
        if len([
            task for task in self.polling.values() if not task.done()
        ]) >= MAX_POLLING_BOTS:
            raise security.SecurityRejected("receiver_capacity_reached", 503)
        async with session_maker() as db:
            row = await db.get(ShopBotReceiver, bot_id)
            if (
                row is None or row.state != "active"
                or row.mode != "polling"
            ):
                raise security.SecurityRejected("invalid_operation_state", 409)
        task = asyncio.create_task(
            self._poll(bot_id), name=f"multi-bot-poll-{bot_id[:8]}",
        )
        self.polling[bot_id] = task

    async def _identity(
        self, bot_id: str, *, allow_settlement: bool = True,
    ):
        """Read an authenticated receiver and current server-side credential."""
        async with session_maker() as db:
            bot = await db.get(ShopBot, bot_id)
            row = await db.get(ShopBotReceiver, bot_id)
            if (
                bot is None or row is None or row.state != "active"
                or bot.runtime_owner != "registry"
                or bot.credential_version != row.credential_version
            ):
                raise security.SecurityRejected("bot_not_active", 409)
            context = await resolve_bot_context(
                db, authenticated_bot_id=bot.id,
                authenticated_platform=Platform(bot.platform),
                authenticated_provider_bot_id=bot.provider_bot_id,
                allow_settlement=allow_settlement,
            )
            token = await db.run_sync(lambda sync: resolve_active_token(
                sync, bot_id=bot_id,
            ))
            return context, token, row.mode, row.next_update_id

    async def dispatch_webhook(
        self, *, binding_id: str, secret: str,
        telegram_header: str | None, payload: Mapping,
    ) -> dict:
        """Authenticate an opaque binding and route to exactly one saved bot."""
        await self.check_lease()
        try:
            binding_id = str(UUID(binding_id))
        except ValueError:
            raise security.SecurityRejected("not_found", 404) from None
        if not isinstance(secret, str) or len(secret) != 43:
            raise security.SecurityRejected("not_found", 404)

        async with session_maker() as db:
            row = await db.scalar(select(ShopBotReceiver).where(
                ShopBotReceiver.binding_id == binding_id,
                ShopBotReceiver.mode == "webhook",
                ShopBotReceiver.state == "active",
            ))
            if row is None:
                raise security.SecurityRejected("not_found", 404)
            digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
            if not hmac.compare_digest(digest, row.webhook_secret_digest):
                raise security.SecurityRejected("not_found", 404)
            bot = await db.get(ShopBot, row.bot_id)
            if bot is None:
                raise security.SecurityRejected("not_found", 404)
            # Telegram's optional server-provided header is mandatory here.
            if bot.platform == "telegram" and (
                telegram_header is None
                or not hmac.compare_digest(telegram_header, secret)
            ):
                raise security.SecurityRejected("not_found", 404)
            bot_id = row.bot_id

        update_id = payload.get("update_id")
        if type(update_id) is not int or update_id < 0:
            raise security.SecurityRejected("invalid_request", 400)
        return await self._process(
            bot_id, update_id=update_id, payload=payload,
        )

    async def _process(
        self, bot_id: str, *, update_id: int, payload: Mapping,
    ) -> dict:
        """Offer durable Runtime input before claiming legacy at-most-once work."""
        context, token, _, _ = await self._identity(bot_id)
        runtime = await try_ingress(context, payload)
        if runtime.get("handled"):
            return runtime
        fresh, status = await claim_update(
            platform=context.platform,
            token=token, update_id=update_id,
            bot_id=bot_id,
        )
        if not fresh:
            return {"status": "duplicate", "receipt_state": status}

        success = False
        result = None
        try:
            async with provider_client(
                context.platform.value, token, bot_id=bot_id,
            ) as provider:
                result = await dispatch(
                    context, provider, payload, runtime_checked=True,
                )
                success = True
        finally:
            # Even if the HTTP connection disappears, retain the result in
            # the DB. A needs_review receipt must never be auto-replayed.
            await asyncio.shield(finish_update(
                platform=context.platform, token=token,
                update_id=update_id, success=success, bot_id=bot_id,
            ))
        if success:
            async with session_maker() as db:
                row = await db.get(
                    ShopBotReceiver, bot_id, with_for_update=True,
                )
                if row and row.state == "active":
                    row.last_received_at = datetime.now(timezone.utc)
                    await db.commit()
        return result or {"status": "ignored"}

    async def _poll(self, bot_id: str) -> None:
        """Drain one bot's provider updates with an isolated persistent offset."""
        while not self.stop_event.is_set():
            try:
                await self.check_lease()
                context, token, mode, offset = await self._identity(bot_id)
                if mode != "polling":
                    return
                async with provider_client(
                    context.platform.value, token, bot_id=bot_id,
                ) as client:
                    if context.platform == Platform.TELEGRAM:
                        info = await asyncio.wait_for(
                            client.get_webhook_info(), 12,
                        )
                        if info.url:
                            raise security.SecurityRejected(
                                "webhook_owned_elsewhere", 409,
                            )
                        updates = await asyncio.wait_for(
                            client.get_updates(
                                offset=offset, limit=50, timeout=10,
                                allowed_updates=[
                                    "message", "callback_query",
                                    "pre_checkout_query",
                                ],
                            ), 18,
                        )
                    else:
                        info = await asyncio.wait_for(client._call(
                            "getWebhookInfo", {},
                        ), 12)
                        if not isinstance(info, dict) or info.get("url"):
                            raise security.SecurityRejected(
                                "webhook_owned_elsewhere", 409,
                            )
                        updates = await asyncio.wait_for(client._call(
                            "getUpdates", {
                                "offset": offset, "timeout": 10,
                                "limit": 50,
                            },
                        ), 18)
                if not isinstance(updates, list):
                    raise security.SecurityRejected(
                        "provider_state_unavailable", 503,
                    )
                for update in updates:
                    if self.stop_event.is_set():
                        return
                    payload = (
                        # The shared dispatcher consumes provider JSON names
                        # such as "from", rather than aiogram's "from_user".
                        update.model_dump(
                            exclude_none=True, mode="json", by_alias=True,
                        )
                        if context.platform == Platform.TELEGRAM else update
                    )
                    if not isinstance(payload, Mapping):
                        raise ValueError("Invalid provider update")
                    identifier = payload.get("update_id")
                    if type(identifier) is not int or identifier < offset:
                        continue
                    try:
                        await self._process(
                            bot_id, update_id=identifier, payload=payload,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # If the claim itself failed before its DB commit,
                        # advancing the provider offset would lose an update.
                        async with session_maker() as receipt_db:
                            receipt_id = await receipt_db.scalar(
                                select(ShopInboundUpdate.id).where(
                                    ShopInboundUpdate.bot_id == bot_id,
                                    ShopInboundUpdate.update_id == identifier,
                                )
                            )
                        if receipt_id is None:
                            raise
                        LOG.warning(
                            "Multi-bot receipt requires review, bot_id=%s",
                            bot_id,
                        )
                    # Update offsets only after processing or durable
                    # quarantine; no second network send on crash recovery.
                    async with session_maker() as db:
                        row = await db.get(
                            ShopBotReceiver, bot_id, with_for_update=True,
                        )
                        if row is None or row.state != "active":
                            return
                        row.next_update_id = max(
                            row.next_update_id, identifier + 1,
                        )
                        await db.commit()
                if not updates:
                    await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Provider exceptions may contain token-bearing URLs; discard.
                LOG.warning(
                    "Polling unavailable for bot_id=%s; no blind replay",
                    bot_id,
                )
                await asyncio.sleep(3)
