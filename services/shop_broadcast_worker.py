"""Durable, at-most-once background campaign dispatch for Telegram and Bale.

A dedicated shared process consumes the PostgreSQL outbox until all queued
recipients are processed. Row locks, provider-specific pacing, persistent
progress and explicit operator states survive ordinary process restarts.
An ambiguous external result is NEVER automatically retried or claimed sent.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import false, or_, select
from sqlalchemy.dialects.postgresql import insert

import config
from channels.bale import BaleTransport
from channels.contracts import BotReply, MediaAttachment, Platform
from channels.telegram import TelegramTransport
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopBroadcastWorkerHeartbeat,
    ShopCampaign,
    ShopCampaignDelivery,
)
from models.shop_multibot import ShopBot
from services.shop_service_controls import service_enabled
from services.shop_broadcast_control import (
    _business_media_ready,
    delivery_counts,
    record_audit,
)
from services.shop_broadcast_rate import reserve_message_slot
from services.shop_broadcast_scope import (
    ready_registry_bot,
    registry_dispatch_enabled,
)
from services.shop_campaigns import CampaignRejected, ShopCampaignService
from services.shop_customer_access import customer_access_allowed

LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedRecipient:
    """One account and delivery reserved exclusively for this worker."""

    delivery_id: int
    campaign_id: int
    platform: Platform
    user_id: int
    bale_mode: str
    bot_id: str
    store_id: str
    identity_id: int
    credential_version: int | None
    provider_bot_id: int | None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CampaignTransport:
    """One explicit bot-bound provider connection; never expose its token."""

    bot_id: str
    platform: Platform
    credential_version: int | None
    token: str = field(repr=False)
    transport: TelegramTransport | BaleTransport = field(repr=False)


@asynccontextmanager
async def registry_transport(
    claim: ClaimedRecipient,
) -> AsyncIterator[CampaignTransport]:
    """Open the exact claimed Registry credential with guaranteed cleanup.

    The CLI injects this factory only after deployment opt-in. Provider
    creation does not activate receivers, verify tokens or send any message.
    """
    from aiohttp import ClientSession, ClientTimeout

    from db import session_maker
    from services.shop_bot_secrets import resolve_active_token
    from services.shop_multibot_client import provider_client

    if not registry_dispatch_enabled():
        raise CampaignRejected("Registry broadcast transport is disabled.")
    async with session_maker() as session:
        bot = await session.scalar(
            ready_registry_bot(
                bot_id=claim.bot_id,
                store_id=claim.store_id,
            )
        )
        if (
            bot is None
            or bot.platform != claim.platform.value
            or bot.credential_version != claim.credential_version
            or bot.provider_bot_id != claim.provider_bot_id
        ):
            raise CampaignRejected("Registry broadcast ownership changed.")
        token = await session.run_sync(
            lambda sync: resolve_active_token(
                sync,
                bot_id=claim.bot_id,
            )
        )

    if claim.platform == Platform.TELEGRAM:
        async with provider_client(
            "telegram",
            token,
            bot_id=claim.bot_id,
        ) as client:
            yield CampaignTransport(
                bot_id=claim.bot_id,
                platform=claim.platform,
                credential_version=claim.credential_version,
                token=token,
                transport=TelegramTransport(client, bot_id=claim.bot_id),
            )
    else:
        async with ClientSession(
            timeout=ClientTimeout(total=120),
            trust_env=False,
        ) as session:
            yield CampaignTransport(
                bot_id=claim.bot_id,
                platform=claim.platform,
                credential_version=claim.credential_version,
                token=token,
                transport=BaleTransport(
                    token,
                    session,
                    bot_id=claim.bot_id,
                    business_mode=claim.bale_mode == "business",
                ),
            )


class BroadcastWorker:
    """Process a bounded number of recipients per loop until queue exhaustion."""

    def __init__(
        self,
        *,
        registry_transport_factory: Callable[
            [ClaimedRecipient], AbstractAsyncContextManager[CampaignTransport]
        ]
        | None = None,
    ) -> None:
        """Use only per-bot authenticated Registry transports."""
        self.registry_transport_factory = registry_transport_factory
        self.worker_id = secrets.token_hex(16)

    async def heartbeat(self) -> None:
        """Expose a low-cost liveness signal without any external API call."""
        from db import session_maker

        now = datetime.now(UTC)
        stmt = insert(ShopBroadcastWorkerHeartbeat).values(
            worker_id=self.worker_id, started_at=now, last_seen_at=now
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ShopBroadcastWorkerHeartbeat.worker_id],
            set_={"last_seen_at": now},
        )
        async with session_maker() as session:
            await session.execute(stmt)
            await session.commit()

    @staticmethod
    async def quarantine_stale() -> int:
        """Mark abandoned in-flight sends uncertain, never requeue them.

        Regularly updated `claimed_at` tracks each confirmed step. A worker
        killed after sending one message leaves an unresolved attempt rather
        than accidentally charging or notifying the customer twice.
        """
        from db import session_maker

        cutoff = datetime.now(UTC) - timedelta(
            seconds=config.SHOP_BROADCAST_STALE_SECONDS
        )
        async with session_maker() as session:
            # Always lock Campaign first, then Delivery, matching the
            # administrator's pause/cancel lock order and preventing deadlocks.
            campaigns = await session.execute(
                select(ShopCampaign)
                .where(
                    select(ShopCampaignDelivery.id)
                    .where(
                        ShopCampaignDelivery.campaign_id == ShopCampaign.id,
                        ShopCampaignDelivery.status == "sending",
                        ShopCampaignDelivery.claimed_at < cutoff,
                    )
                    .exists()
                )
                .order_by(ShopCampaign.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
            changed = 0
            for campaign in campaigns.scalars().all():
                changed_campaign = 0
                rows = await session.execute(
                    select(ShopCampaignDelivery)
                    .where(
                        ShopCampaignDelivery.campaign_id == campaign.id,
                        ShopCampaignDelivery.status == "sending",
                        ShopCampaignDelivery.claimed_at < cutoff,
                    )
                    .order_by(ShopCampaignDelivery.id)
                    .limit(25)
                    .with_for_update(skip_locked=True)
                )
                for delivery in rows.scalars().all():
                    delivery.status = "unknown"
                    delivery.last_error_code = "stale_after_restart"
                    record_audit(
                        session,
                        campaign_id=campaign.id,
                        delivery_id=delivery.id,
                        actor="worker",
                        action="quarantine",
                        old_status="sending",
                        new_status="unknown",
                        reason="In-flight delivery exceeded stale threshold.",
                    )
                    changed += 1
                    changed_campaign += 1
                if changed_campaign and campaign.status == "sending":
                    campaign.status = "paused"
                    campaign.paused_at = datetime.now(UTC)
                    campaign.last_error_code = "stale_after_restart"
            if changed:
                await session.commit()
            return changed

    async def _claim_one(self) -> ClaimedRecipient | None:
        """Lock one active campaign and one queued delivery before dispatch."""
        from db import session_maker

        async with session_maker() as session:
            registry_enabled = (
                registry_dispatch_enabled()
                and self.registry_transport_factory is not None
            )
            if not registry_enabled:
                return None
            registry_owner = (
                (ShopCampaign.bot_id == ShopIdentity.bot_id)
                & ready_registry_bot(
                    bot_id=ShopIdentity.bot_id,
                    store_id=ShopCampaign.store_id,
                )
                .where(
                    ShopBot.platform == ShopIdentity.platform,
                )
                .correlate(ShopIdentity, ShopCampaign)
                .exists()
                if registry_enabled
                else false()
            )
            scope = (
                ShopCampaignDelivery.status == "queued",
                ShopCampaignDelivery.bot_id == ShopIdentity.bot_id,
                ShopIdentity.store_id == ShopCampaign.store_id,
                or_(
                    ShopCampaign.audience == "all",
                    ShopCampaign.audience == ShopIdentity.platform,
                ),
                registry_owner,
            )
            active = await session.scalar(
                select(ShopCampaign)
                .where(
                    ShopCampaign.status == "sending",
                    select(ShopCampaignDelivery.id)
                    .join(
                        ShopIdentity,
                        ShopIdentity.id == ShopCampaignDelivery.identity_id,
                    )
                    .where(
                        ShopCampaignDelivery.campaign_id == ShopCampaign.id,
                        *scope,
                    )
                    .exists(),
                )
                .order_by(ShopCampaign.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if active is None:
                return None
            row = await session.execute(
                select(ShopCampaignDelivery, ShopIdentity)
                .join(
                    ShopIdentity,
                    ShopIdentity.id == ShopCampaignDelivery.identity_id,
                )
                .join(ShopCampaign, ShopCampaign.id == ShopCampaignDelivery.campaign_id)
                .where(
                    ShopCampaignDelivery.campaign_id == active.id,
                    *scope,
                )
                .order_by(ShopCampaignDelivery.id)
                .limit(1)
                .with_for_update(of=ShopCampaignDelivery, skip_locked=True)
            )
            pair = row.one_or_none()
            if pair is None:
                return None
            delivery, identity = pair
            bot = await session.get(ShopBot, identity.bot_id)
            # A revoked opt-in is terminal before any factory sees the claim.
            skip_reason = (
                "consent_revoked"
                if not identity.allow_announcements
                or not await customer_access_allowed(session, identity)
                else None
            )
            delivery.status = "skipped" if skip_reason else "sending"
            delivery.last_error_code = skip_reason
            delivery.worker_id = self.worker_id
            delivery.claimed_at = datetime.now(UTC)
            delivery.completed_steps = 0
            await session.commit()
            return ClaimedRecipient(
                delivery_id=delivery.id,
                campaign_id=active.id,
                platform=Platform(identity.platform),
                user_id=identity.platform_user_id,
                bale_mode=active.bale_mode,
                bot_id=identity.bot_id,
                store_id=active.store_id,
                identity_id=identity.id,
                credential_version=bot.credential_version if bot else None,
                provider_bot_id=bot.provider_bot_id if bot else None,
                skip_reason=skip_reason,
            )

    async def _step_allowed(
        self,
        claim: ClaimedRecipient,
    ) -> tuple[bool, int]:
        """Check current opt-in and pause/cancel state before each API call."""
        from db import session_maker

        async with session_maker() as session:
            result = await session.execute(
                select(ShopCampaignDelivery, ShopIdentity, ShopCampaign)
                .join(
                    ShopIdentity,
                    ShopIdentity.id == ShopCampaignDelivery.identity_id,
                )
                .join(
                    ShopCampaign,
                    ShopCampaign.id == ShopCampaignDelivery.campaign_id,
                )
                .where(
                    ShopCampaignDelivery.id == claim.delivery_id,
                    ShopCampaignDelivery.campaign_id == claim.campaign_id,
                    ShopCampaignDelivery.worker_id == self.worker_id,
                    ShopCampaignDelivery.status == "sending",
                )
            )
            row = result.one_or_none()
            if row is None:
                return False, 0
            delivery, identity, campaign = row
            same_owner = (
                identity.id == claim.identity_id
                and identity.bot_id == claim.bot_id
                and identity.store_id == claim.store_id
                and identity.platform == claim.platform.value
                and identity.platform_user_id == claim.user_id
                and delivery.bot_id == claim.bot_id
                and campaign.store_id == claim.store_id
                and campaign.bale_mode == claim.bale_mode
                and campaign.audience in ("all", claim.platform.value)
            )
            bot = await session.scalar(
                ready_registry_bot(
                    bot_id=claim.bot_id,
                    store_id=claim.store_id,
                )
            )
            runtime_allowed = (
                registry_dispatch_enabled()
                and self.registry_transport_factory is not None
                and bot is not None
                and bot.platform == claim.platform.value
                and bot.credential_version == claim.credential_version
                and bot.provider_bot_id == claim.provider_bot_id
                and campaign.bot_id == claim.bot_id
            )
            return (
                service_enabled("broadcast")
                and same_owner
                and runtime_allowed
                and campaign.status == "sending"
                and await customer_access_allowed(session, identity)
                and identity.allow_announcements is True,
                delivery.completed_steps,
            )

    @staticmethod
    async def _mark_step(delivery_id: int) -> None:
        """Persist a confirmed text/media send before attempting another step."""
        from db import session_maker

        async with session_maker() as session:
            delivery = await session.scalar(
                select(ShopCampaignDelivery)
                .where(
                    ShopCampaignDelivery.id == delivery_id,
                    ShopCampaignDelivery.status == "sending",
                )
                .with_for_update()
            )
            if delivery is None:
                raise RuntimeError("In-flight delivery was unexpectedly changed.")
            delivery.completed_steps += 1
            delivery.claimed_at = datetime.now(UTC)
            await session.commit()

    @staticmethod
    async def _paid_reservation(claim: ClaimedRecipient) -> None:
        """Reserve *one* billable Bale API message before the network attempt."""
        if claim.platform != Platform.BALE or claim.bale_mode != "business":
            return
        if not (
            service_enabled("broadcast")
            and service_enabled("bale-paid-broadcast")
            and config.BALE_BROADCAST_MODE == "business"
        ):
            raise CampaignRejected("مجوز پرداخت هزینه Business API غیرفعال است.")
        from db import session_maker

        async with session_maker() as session:
            campaign = await session.scalar(
                select(ShopCampaign)
                .where(ShopCampaign.id == claim.campaign_id)
                .with_for_update()
            )
            if (
                campaign is None
                or campaign.status != "sending"
                or campaign.bale_mode != "business"
                or campaign.max_paid_calls <= 0
                or campaign.paid_calls_reserved >= campaign.max_paid_calls
            ):
                raise CampaignRejected("سقف هزینه Business API تمام شده است.")
            campaign.paid_calls_reserved += 1
            await session.commit()

    @staticmethod
    async def _complete(
        delivery_id: int,
        *,
        status: str,
        error_code: str | None = None,
    ) -> None:
        """Finalize one recipient and calculate campaign completion atomically."""
        from db import session_maker

        async with session_maker() as session:
            # Identify the parent without locking, then lock campaign first.
            # This matches control transitions and stale-delivery quarantine.
            delivery_id_parent = await session.scalar(
                select(ShopCampaignDelivery.campaign_id).where(
                    ShopCampaignDelivery.id == delivery_id
                )
            )
            if delivery_id_parent is None:
                return
            campaign = await session.scalar(
                select(ShopCampaign)
                .where(ShopCampaign.id == delivery_id_parent)
                .with_for_update()
            )
            delivery = await session.scalar(
                select(ShopCampaignDelivery)
                .where(ShopCampaignDelivery.id == delivery_id)
                .with_for_update()
            )
            if delivery is None or delivery.status != "sending":
                return
            delivery.status = status
            delivery.last_error_code = error_code
            if status == "sent":
                delivery.sent_at = datetime.now(UTC)
            if status == "unknown":
                record_audit(
                    session,
                    campaign_id=delivery.campaign_id,
                    delivery_id=delivery.id,
                    actor="worker",
                    action="delivery_uncertain",
                    old_status="sending",
                    new_status="unknown",
                    reason=error_code,
                )
                if campaign is not None and campaign.status == "sending":
                    campaign.status = "paused"
                    campaign.paused_at = datetime.now(UTC)
                    campaign.last_error_code = error_code or "unknown_delivery"
            await session.commit()

    @staticmethod
    async def finalize_campaigns() -> int:
        """Finish campaigns with no queued/in-flight recipients, or flag unknowns."""
        from db import session_maker

        async with session_maker() as session:
            result = await session.execute(
                select(ShopCampaign)
                .where(ShopCampaign.status == "sending")
                .order_by(ShopCampaign.id)
                .limit(40)
                .with_for_update(skip_locked=True)
            )
            done = 0
            for campaign in result.scalars().all():
                counts = await delivery_counts(session, campaign.id)
                if counts.get("queued") or counts.get("sending"):
                    continue
                old = campaign.status
                campaign.status = (
                    "needs_review" if counts.get("unknown") else "completed"
                )
                campaign.finished_at = datetime.now(UTC)
                record_audit(
                    session,
                    campaign_id=campaign.id,
                    actor="worker",
                    action="finish",
                    old_status=old,
                    new_status=campaign.status,
                )
                done += 1
            if done:
                await session.commit()
            return done

    @asynccontextmanager
    async def _outbound(
        self,
        claim: ClaimedRecipient,
    ) -> AsyncIterator[CampaignTransport]:
        """Open only the exact claimed bot credential and reject scope changes."""
        if not registry_dispatch_enabled() or self.registry_transport_factory is None:
            raise CampaignRejected("Registry broadcast transport is disabled.")
        async with self.registry_transport_factory(claim) as outbound:
            if (
                outbound.bot_id != claim.bot_id
                or outbound.platform != claim.platform
                or outbound.credential_version != claim.credential_version
                or getattr(outbound.transport, "bot_id", None) != claim.bot_id
            ):
                raise CampaignRejected("Registry transport ownership mismatch.")
            yield outbound

    async def _send_one(
        self,
        claim: ClaimedRecipient,
        *,
        text: str,
        attachments: tuple[MediaAttachment, ...],
    ) -> None:
        """Send text and attachments using only the explicit scoped transport."""
        allowed, progress = await self._step_allowed(claim)
        if not allowed:
            await self._complete(
                claim.delivery_id,
                status="unknown" if progress else "skipped",
                error_code="paused_or_consent_revoked",
            )
            return
        async with self._outbound(claim) as outbound:
            await self._send_steps(
                claim,
                outbound=outbound,
                text=text,
                attachments=attachments,
            )

    async def _send_steps(
        self,
        claim: ClaimedRecipient,
        *,
        outbound: CampaignTransport,
        text: str,
        attachments: tuple[MediaAttachment, ...],
    ) -> None:
        """Recheck ownership and consent around every durable pacing wait."""
        all_steps = (None, *attachments)
        for step in all_steps:
            allowed, progress = await self._step_allowed(claim)
            if not allowed:
                await self._complete(
                    claim.delivery_id,
                    status="unknown" if progress else "skipped",
                    error_code="paused_or_consent_revoked",
                )
                return
            # Each Bot API *message* has one global and one private-chat slot.
            await reserve_message_slot(
                platform=claim.platform,
                token=outbound.token,
                bot_id=claim.bot_id,
                user_id=claim.user_id,
                bale_mode=claim.bale_mode,
            )
            allowed, progress = await self._step_allowed(claim)
            if not allowed:
                await self._complete(
                    claim.delivery_id,
                    status="unknown" if progress else "skipped",
                    error_code="consent_changed_during_rate_wait",
                )
                return

            # Charge reservations are made before the request, even if the
            # provider times out: no hidden retries or unbounded fees.
            await self._paid_reservation(claim)
            # Reserving the paid budget may wait for a campaign-row lock.
            # Keep that conservative reservation, but never treat it as
            # consent if the recipient or operations changed meanwhile.
            allowed, progress = await self._step_allowed(claim)
            if not allowed:
                await self._complete(
                    claim.delivery_id,
                    status="unknown" if progress else "skipped",
                    error_code="consent_changed_during_budget_wait",
                )
                return
            if step is None:
                reply = BotReply(text)
                await outbound.transport.send(claim.user_id, reply)
            else:
                await outbound.transport.send_media(claim.user_id, step)
            await self._mark_step(claim.delivery_id)
            await self.heartbeat()

        await self._complete(claim.delivery_id, status="sent")

    async def process_next(self) -> bool:
        """Consume one available recipient; errors pause, never blindly retry."""
        if not (
            service_enabled("broadcast")
        ):
            return False

        claim = await self._claim_one()
        if claim is None:
            return False
        if claim.skip_reason is not None:
            return True

        try:
            from db import session_maker

            async with session_maker() as session:
                campaign = await session.get(ShopCampaign, claim.campaign_id)
                attachments = await ShopCampaignService._attachments(session, campaign)
                if claim.platform == Platform.BALE and claim.bale_mode == "business":
                    await _business_media_ready(session, campaign)
                body = campaign.text
            await self._send_one(claim, text=body, attachments=attachments)
        except asyncio.CancelledError:
            # Cancellation during a network call is always an uncertain
            # external outcome. Preserve it and re-raise for clean shutdown.
            await self._complete(
                claim.delivery_id,
                status="unknown",
                error_code="worker_cancelled",
            )
            raise
        except Exception as error:  # noqa: BLE001 - Quarantine every unclassified outcome.
            # Do not log provider errors containing token-bearing URLs, chat
            # text, or external message bodies.
            LOG.warning(
                "Broadcast paused after uncertain delivery: campaign=%s "
                "delivery=%s error_type=%s",
                claim.campaign_id,
                claim.delivery_id,
                type(error).__name__,
            )
            await self._complete(
                claim.delivery_id,
                status="unknown",
                error_code="outbound_or_preflight_error",
            )
        return True

    async def run_forever(self) -> None:
        """Drain every active campaign, polling only when no work is queued."""
        while True:
            await self.heartbeat()
            if not service_enabled("broadcast"):
                await asyncio.sleep(config.SHOP_BROADCAST_POLL_SECONDS)
                continue
            await self.quarantine_stale()
            did_work = False
            for _ in range(10):
                if not await self.process_next():
                    break
                did_work = True
            await self.finalize_campaigns()
            if not did_work:
                await asyncio.sleep(config.SHOP_BROADCAST_POLL_SECONDS)
