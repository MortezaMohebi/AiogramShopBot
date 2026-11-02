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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.bale import BaleTransport
from channels.contracts import BotReply, MediaAttachment, Platform
from channels.telegram import TelegramTransport
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopCampaign, ShopCampaignDelivery,
)
from services.shop_broadcast_control import (
    _business_media_ready, delivery_counts, record_audit,
)
from services.shop_broadcast_rate import reserve_message_slot
from services.shop_campaigns import CampaignRejected, ShopCampaignService


@dataclass(frozen=True, slots=True)
class ClaimedRecipient:
    """One account and delivery reserved exclusively for this worker."""

    delivery_id: int
    campaign_id: int
    platform: Platform
    user_id: int
    bale_mode: str


class BroadcastWorker:
    """Process a bounded number of recipients per loop until queue exhaustion."""

    def __init__(
        self,
        *,
        telegram: TelegramTransport | None,
        bale_session,
    ) -> None:
        """Reuse one Telegram Bot and one optional Bale aiohttp client."""
        self.telegram = telegram
        self.bale_session = bale_session
        self.worker_id = secrets.token_hex(16)

    @staticmethod
    async def quarantine_stale() -> int:
        """Mark abandoned in-flight sends uncertain, never requeue them.

        Regularly updated `claimed_at` tracks each confirmed step. A worker
        killed after sending one message leaves an unresolved attempt rather
        than accidentally charging or notifying the customer twice.
        """
        from db import session_maker

        cutoff = datetime.now(timezone.utc) - timedelta(
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
                    ).exists()
                )
                .order_by(ShopCampaign.id)
                .limit(25)
                .with_for_update(skip_locked=True)
            )
            changed = 0
            for campaign in campaigns.scalars().all():
                rows = await session.execute(
                    select(ShopCampaignDelivery).where(
                        ShopCampaignDelivery.campaign_id == campaign.id,
                        ShopCampaignDelivery.status == "sending",
                        ShopCampaignDelivery.claimed_at < cutoff,
                    ).order_by(ShopCampaignDelivery.id)
                    .limit(25).with_for_update(skip_locked=True)
                )
                for delivery in rows.scalars().all():
                    delivery.status = "unknown"
                    delivery.last_error_code = "stale_after_restart"
                    record_audit(
                        session, campaign_id=campaign.id,
                        delivery_id=delivery.id, actor="worker",
                        action="quarantine", old_status="sending",
                        new_status="unknown",
                        reason="In-flight delivery exceeded stale threshold.",
                    )
                    changed += 1
                if changed and campaign.status == "sending":
                    campaign.status = "paused"
                    campaign.paused_at = datetime.now(timezone.utc)
                    campaign.last_error_code = "stale_after_restart"
            if changed:
                await session.commit()
            return changed

    async def _claim_one(self) -> ClaimedRecipient | None:
        """Lock one active campaign and one queued delivery before dispatch."""
        from db import session_maker

        async with session_maker() as session:
            active = await session.scalar(
                select(ShopCampaign)
                .where(
                    ShopCampaign.status == "sending",
                    select(ShopCampaignDelivery.id)
                    .where(
                        ShopCampaignDelivery.campaign_id == ShopCampaign.id,
                        ShopCampaignDelivery.status == "queued",
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
                .where(
                    ShopCampaignDelivery.campaign_id == active.id,
                    ShopCampaignDelivery.status == "queued",
                )
                .order_by(ShopCampaignDelivery.id)
                .limit(1)
                .with_for_update(
                    of=ShopCampaignDelivery, skip_locked=True
                )
            )
            pair = row.one_or_none()
            if pair is None:
                return None
            delivery, identity = pair
            if identity.platform not in ("telegram", "bale"):
                delivery.status = "skipped"
                delivery.last_error_code = "unknown_platform"
                await session.commit()
                return None

            delivery.status = "sending"
            delivery.worker_id = self.worker_id
            delivery.claimed_at = datetime.now(timezone.utc)
            delivery.completed_steps = 0
            await session.commit()
            return ClaimedRecipient(
                delivery_id=delivery.id,
                campaign_id=active.id,
                platform=Platform(identity.platform),
                user_id=identity.platform_user_id,
                bale_mode=active.bale_mode,
            )

    async def _step_allowed(
        self, claim: ClaimedRecipient,
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
            return (
                campaign.status == "sending"
                and identity.is_blocked is False
                and identity.allow_announcements is True,
                delivery.completed_steps,
            )

    @staticmethod
    async def _mark_step(delivery_id: int) -> None:
        """Persist a confirmed text/media send before attempting another step."""
        from db import session_maker

        async with session_maker() as session:
            delivery = await session.scalar(
                select(ShopCampaignDelivery).where(
                    ShopCampaignDelivery.id == delivery_id,
                    ShopCampaignDelivery.status == "sending",
                ).with_for_update()
            )
            if delivery is None:
                raise RuntimeError("In-flight delivery was unexpectedly changed.")
            delivery.completed_steps += 1
            delivery.claimed_at = datetime.now(timezone.utc)
            await session.commit()

    @staticmethod
    async def _paid_reservation(claim: ClaimedRecipient) -> None:
        """Reserve *one* billable Bale API message before the network attempt."""
        if claim.platform != Platform.BALE or claim.bale_mode != "business":
            return
        if not (
            config.SHOP_CAMPAIGN_DISPATCH_ENABLED
            and config.BALE_BROADCAST_PAID_ENABLED
            and config.BALE_BROADCAST_MODE == "business"
        ):
            raise CampaignRejected("مجوز پرداخت هزینه Business API غیرفعال است.")
        from db import session_maker

        async with session_maker() as session:
            campaign = await session.scalar(
                select(ShopCampaign).where(
                    ShopCampaign.id == claim.campaign_id
                ).with_for_update()
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
                select(ShopCampaign).where(
                    ShopCampaign.id == delivery_id_parent
                ).with_for_update()
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
                delivery.sent_at = datetime.now(timezone.utc)
            if status == "unknown":
                record_audit(
                    session, campaign_id=delivery.campaign_id,
                    delivery_id=delivery.id,
                    actor="worker", action="delivery_uncertain",
                    old_status="sending", new_status="unknown",
                    reason=error_code,
                )
                if campaign is not None and campaign.status == "sending":
                    campaign.status = "paused"
                    campaign.paused_at = datetime.now(timezone.utc)
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
                campaign.finished_at = datetime.now(timezone.utc)
                record_audit(
                    session, campaign_id=campaign.id,
                    actor="worker", action="finish",
                    old_status=old, new_status=campaign.status,
                )
                done += 1
            if done:
                await session.commit()
            return done

    async def _send_one(
        self, claim: ClaimedRecipient, *,
        text: str, attachments: tuple[MediaAttachment, ...]
    ) -> None:
        """Send text and attachments with durable pacing at every API step."""
        if claim.platform == Platform.TELEGRAM:
            if self.telegram is None:
                raise CampaignRejected("Telegram transport is unavailable.")
            token = self.telegram.bot.token
        else:
            if not config.BALE_BOT_TOKEN or self.bale_session is None:
                raise CampaignRejected("Bale transport is unavailable.")
            token = config.BALE_BOT_TOKEN

        bale = (
            BaleTransport(
                config.BALE_BOT_TOKEN,
                self.bale_session,
                business_mode=claim.bale_mode == "business",
            )
            if claim.platform == Platform.BALE else None
        )
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
                token=token,
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
            if step is None:
                reply = BotReply(text)
                if claim.platform == Platform.TELEGRAM:
                    await self.telegram.send(claim.user_id, reply)
                else:
                    await bale.send(claim.user_id, reply)
            elif claim.platform == Platform.TELEGRAM:
                await self.telegram.send_media(claim.user_id, step)
            else:
                await bale.send_media(claim.user_id, step)
            await self._mark_step(claim.delivery_id)

        await self._complete(claim.delivery_id, status="sent")

    async def process_next(self) -> bool:
        """Consume one available recipient; errors pause, never blindly retry."""
        if not (
            config.SHOP_BROADCAST_WORKER_ENABLED
            and config.SHOP_CAMPAIGN_DISPATCH_ENABLED
        ):
            return False

        claim = await self._claim_one()
        if claim is None:
            return False

        try:
            from db import session_maker

            async with session_maker() as session:
                campaign = await session.get(ShopCampaign, claim.campaign_id)
                attachments = await ShopCampaignService._attachments(
                    session, campaign
                )
                if (
                    claim.platform == Platform.BALE
                    and claim.bale_mode == "business"
                ):
                    await _business_media_ready(session, campaign)
                body = campaign.text
            await self._send_one(
                claim, text=body, attachments=attachments
            )
        except asyncio.CancelledError:
            # Cancellation during a network call is always an uncertain
            # external outcome. Preserve it and re-raise for clean shutdown.
            await self._complete(
                claim.delivery_id, status="unknown",
                error_code="worker_cancelled",
            )
            raise
        except Exception as error:
            # Do not log provider errors containing token-bearing URLs, chat
            # text, or external message bodies.
            logging.warning(
                "Broadcast paused after uncertain delivery: campaign=%s "
                "delivery=%s error_type=%s",
                claim.campaign_id, claim.delivery_id, type(error).__name__,
            )
            await self._complete(
                claim.delivery_id, status="unknown",
                error_code="outbound_or_preflight_error",
            )
        return True

    async def run_forever(self) -> None:
        """Drain every active campaign, polling only when no work is queued."""
        while True:
            await self.quarantine_stale()
            did_work = False
            for _ in range(10):
                if not await self.process_next():
                    break
                did_work = True
            await self.finalize_campaigns()
            if not did_work:
                await asyncio.sleep(config.SHOP_BROADCAST_POLL_SECONDS)
