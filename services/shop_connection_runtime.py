"""Supervised, durable Telegram/Bale receivers with tracked mode changes.

Only this single-replica worker can register/remove webhooks. It never drops
pending updates. An interrupted provider call becomes needs_review, not a
blind automatic retry. No Docker socket or shell commands are used.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sqlalchemy import select, text
from starlette.requests import Request

import config
from db import engine, session_maker
from models.shop_admin_control import ConnectionChange, ConnectionConfig
from services.shop_admin_security import SecurityRejected, has_permission
from services.shop_connection_control import transition

log = logging.getLogger(__name__)


class ConnectionSupervisor:
    """Own exactly one provider-receiver pair under a PostgreSQL lease."""

    def __init__(self, app):
        """Retain the existing bot dispatchers and reusable Bale HTTP client."""
        self.app = app
        self.tasks: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
        self.worker = None
        self.lease = None
        self.lease_pid = None
        self.lease_mutex = asyncio.Lock()
        self.stopped = asyncio.Event()
        self.modes = {"telegram": config.TELEGRAM_UPDATE_MODE, "bale": "webhook"}

    async def start(self) -> None:
        """Restore verified receivers and quarantine interrupted operations."""
        self.lease = await engine.connect()
        owned = await self.lease.scalar(text("SELECT pg_try_advisory_lock(90211004)"))
        if not owned:
            await self.lease.close()
            self.lease = None
            raise RuntimeError("Another receiver process owns this database")
        self.lease_pid = await self.lease.scalar(text("SELECT pg_backend_pid()"))
        await self.lease.commit()
        async with session_maker() as db:
            for platform, mode in self.modes.items():
                row = await db.get(ConnectionConfig, platform)
                if row is None:
                    db.add(ConnectionConfig(platform=platform, mode=mode, version=1, next_update_id=0))
                else:
                    self.modes[platform] = row.mode
            interrupted = (await db.scalars(select(ConnectionChange).where(
                ConnectionChange.state == "applying"))).all()
            for row in interrupted:
                await db.run_sync(lambda sync: transition(sync, row, "needs_review",
                    actor_id=row.staff_id, error_code="interrupted_operation"))
            await db.commit()
        self.app.state.connection_supervisor = self
        config.TELEGRAM_UPDATE_MODE = self.modes["telegram"]
        # A conflicting external webhook is never silently taken over on boot.
        for platform, mode in self.modes.items():
            if mode == "polling":
                try:
                    if not await self.webhook_url(platform):
                        await self.start_polling(platform)
                    else:
                        log.error("Receiver not resumed: external webhook conflict (%s)", platform)
                except Exception:
                    log.error("Receiver not resumed: provider check unavailable (%s)", platform)
        self.worker = asyncio.create_task(self.run(), name="shop-connection-control")

    async def check_lease(self) -> None:
        """Stop rather than reconnect and continue after losing receiver ownership."""
        async with self.lease_mutex:
            try:
                if self.lease is None or self.lease.closed or self.lease.invalidated:
                    raise RuntimeError("Receiver lease lost")
                pid = await asyncio.wait_for(self.lease.scalar(text("SELECT pg_backend_pid()")), 3)
                await self.lease.commit()
                if pid != self.lease_pid:
                    raise RuntimeError("Receiver database connection changed")
            except Exception:
                self.stopped.set()
                for _, stop in self.tasks.values():
                    stop.set()
                raise SecurityRejected("receiver_lease_lost", 503) from None

    async def close(self) -> None:
        """Drain bounded I/O and always release resources on shutdown."""
        self.stopped.set()
        try:
            if self.worker:
                try:
                    await asyncio.wait_for(asyncio.shield(self.worker), 30)
                except asyncio.TimeoutError:
                    self.worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await self.worker
            for platform in list(self.tasks):
                try:
                    await self.stop_polling(platform)
                except SecurityRejected:
                    # Receipt stays processing/needs_review; never replay blindly.
                    task, _ = self.tasks.pop(platform)
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
        finally:
            if self.lease is not None:
                try:
                    if not self.lease.closed and not self.lease.invalidated:
                        await self.lease.execute(text("SELECT pg_advisory_unlock(90211004)"))
                        await self.lease.commit()
                finally:
                    await self.lease.close()

    def provider(self, platform: str):
        """Use only the deployment-configured provider, never a user URL."""
        if platform == "telegram":
            from bot import bot
            return bot
        from channels.bale import BaleTransport
        if not config.BALE_BOT_TOKEN or self.app.state.bale_http_client is None:
            raise SecurityRejected("provider_not_configured", 409)
        return BaleTransport(config.BALE_BOT_TOKEN, self.app.state.bale_http_client)

    async def webhook_url(self, platform: str) -> str:
        """Read registered webhook state; unavailable is not equivalent to empty."""
        provider = self.provider(platform)
        if platform == "telegram":
            info = await asyncio.wait_for(provider.get_webhook_info(), 8)
            return info.url
        info = await asyncio.wait_for(provider._call("getWebhookInfo", {}), 8)
        if not isinstance(info, dict) or not isinstance(info.get("url"), str):
            raise SecurityRejected("provider_state_unavailable", 503)
        return info["url"]

    def expected_url(self, platform: str) -> str:
        """Keep the confidential Bale path out of logs and audit details."""
        if platform == "telegram":
            return config.WEBHOOK_URL
        return f"{config.WEBHOOK_HOST}/webhooks/bale/{config.BALE_WEBHOOK_SECRET}"

    async def stop_polling(self, platform: str) -> None:
        """Drain in-flight processing rather than cancelling a message send."""
        entry = self.tasks.get(platform)
        if not entry:
            return
        task, stop = entry
        stop.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), 25)
        except asyncio.TimeoutError:
            # Do not start a second receiver while this one might still run.
            raise SecurityRejected("receiver_drain_timeout", 503) from None
        self.tasks.pop(platform, None)

    async def start_polling(self, platform: str) -> None:
        """Start one durable-offset loop after provider state is verified."""
        if platform in self.tasks:
            return
        stop = asyncio.Event()
        task = asyncio.create_task(self.poll(platform, stop), name=f"shop-poll-{platform}")
        self.tasks[platform] = (task, stop)

    async def apply(self, platform: str, requested: str, verification_only=False) -> None:
        """Switch modes with ownership checks and observed-state verification."""
        await self.check_lease()
        provider = self.provider(platform)
        actual = await self.webhook_url(platform)
        expected = self.expected_url(platform)
        if actual and actual != expected:
            raise SecurityRejected("webhook_owned_elsewhere", 409)
        if verification_only:
            matches = (not actual) if requested == "polling" else (actual == expected)
            if not matches:
                raise SecurityRejected("provider_state_mismatch", 409)
        elif requested == "polling":
            if actual:
                if platform == "telegram":
                    await asyncio.wait_for(provider.delete_webhook(drop_pending_updates=False), 8)
                else:
                    await asyncio.wait_for(provider._call("deleteWebhook", {}), 8)
            if await self.webhook_url(platform):
                raise SecurityRejected("provider_state_mismatch", 409)
        else:
            await self.stop_polling(platform)
            if not expected.startswith("https://"):
                raise SecurityRejected("webhook_url_invalid", 422)
            if platform == "telegram":
                await asyncio.wait_for(provider.set_webhook(
                    url=expected, secret_token=config.WEBHOOK_SECRET_TOKEN,
                    drop_pending_updates=False, max_connections=2), 8)
            else:
                await asyncio.wait_for(provider._call("setWebhook", {"url": expected}), 8)
            if await self.webhook_url(platform) != expected:
                raise SecurityRejected("provider_state_mismatch", 409)
        if requested == "polling":
            await self.start_polling(platform)
        else:
            await self.stop_polling(platform)
        self.modes[platform] = requested
        if platform == "telegram":
            config.TELEGRAM_UPDATE_MODE = requested

    async def run(self) -> None:
        """Claim one queued operation; never auto-replay uncertain outcomes."""
        while not self.stopped.is_set():
            try:
                await self.check_lease()
                async with session_maker() as db:
                    row = await db.scalar(select(ConnectionChange).where(
                        ConnectionChange.state == "queued").order_by(
                            ConnectionChange.created_at).with_for_update(skip_locked=True).limit(1))
                    if row is None:
                        await asyncio.sleep(1)
                        continue
                    from models.shop_staff import ShopStaff
                    approver = await db.get(ShopStaff, row.approved_by or row.staff_id)
                    if approver is None or not approver.is_active or not has_permission(approver.role, "bots.apply"):
                        await db.run_sync(lambda sync: transition(sync, row, "failed", actor_id=row.staff_id, error_code="authorization_revoked"))
                        await db.commit()
                        continue
                    await db.run_sync(lambda sync: transition(sync, row, "applying", actor_id=approver.id))
                    identifier, platform, mode, actor = row.id, row.platform, row.requested_mode, approver.id
                    verification = row.verification_only
                    await db.commit()
                state, code = "succeeded", None
                try:
                    await self.apply(platform, mode, verification)
                except SecurityRejected as error:
                    state, code = "needs_review", error.code
                except Exception:
                    state, code = "needs_review", "provider_outcome_unknown"
                async with session_maker() as db:
                    row = await db.scalar(select(ConnectionChange).where(
                        ConnectionChange.id == identifier).with_for_update())
                    await db.run_sync(lambda sync: transition(sync, row, state,
                        actor_id=actor, error_code=code))
                    await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Sanitized: third-party exceptions can contain secret URLs.
                log.error("Connection control operation requires investigation")
                await asyncio.sleep(2)

    async def poll(self, platform: str, stop: asyncio.Event) -> None:
        """Persist offsets only after an update receipt is durably finalized."""
        from channels.contracts import Platform
        from services.shop_updates import claim_update, finish_update
        from bot import dp, _process_bale_update
        provider = self.provider(platform)
        token = config.TOKEN if platform == "telegram" else config.BALE_BOT_TOKEN
        while not stop.is_set() and not self.stopped.is_set():
            try:
                await self.check_lease()
                async with session_maker() as db:
                    cfg = await db.get(ConnectionConfig, platform)
                    offset = cfg.next_update_id
                if platform == "telegram":
                    updates = await asyncio.wait_for(provider.get_updates(offset=offset, timeout=10, limit=50), 15)
                else:
                    updates = await asyncio.wait_for(provider._call("getUpdates", {"offset": offset, "timeout": 10, "limit": 50}), 15)
                if not isinstance(updates, list):
                    raise ValueError("Invalid update list")
                for update in updates:
                    if stop.is_set():
                        break
                    identifier = update.update_id if platform == "telegram" else update.get("update_id")
                    if type(identifier) is not int or identifier < offset:
                        continue
                    fresh, _ = await claim_update(platform=Platform(platform), token=token, update_id=identifier)
                    if fresh:
                        success = False
                        try:
                            if platform == "telegram":
                                await dp.feed_update(provider, update)
                            else:
                                await _process_bale_update(Request({"type": "http", "app": self.app}), update)
                            success = True
                        finally:
                            await finish_update(platform=Platform(platform), token=token,
                                                update_id=identifier, success=success)
                    async with session_maker() as db:
                        cfg = await db.get(ConnectionConfig, platform)
                        cfg.next_update_id = max(cfg.next_update_id, identifier + 1)
                        await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Polling interrupted; durable receipt retained (%s)", platform)
                await asyncio.sleep(2)
