"""Durable broadcast campaign lifecycle and explicit paid-Bale approvals.

Only this service may transition a campaign into or out of background sending.
A manager approves recipients and a frozen cost ceiling before start; the
worker, not the web request, sends every queued recipient.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import false, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.media_policy import bale_media_method
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopCampaign,
    ShopCampaignAudit,
    ShopCampaignDelivery,
)
from models.shop_multibot import ShopBot
from services.shop_broadcast_scope import ready_registry_bot, registry_dispatch_enabled
from services.shop_campaigns import (
    CampaignRejected,
    ShopCampaignService,
    require_campaign_scope,
)
from services.shop_media_delivery import bot_fingerprint, cached_file_id


def record_audit(
    session: AsyncSession,
    *,
    campaign_id: int,
    actor: str,
    action: str,
    old_status: str,
    new_status: str,
    reason: str | None = None,
    delivery_id: int | None = None,
) -> None:
    """Append a readable operator or worker decision to the immutable audit."""
    session.add(
        ShopCampaignAudit(
            campaign_id=campaign_id,
            delivery_id=delivery_id,
            actor=actor[:120],
            action=action[:32],
            previous_status=old_status[:24],
            new_status=new_status[:24],
            reason=reason[:255] if reason else None,
        )
    )


async def delivery_counts(session: AsyncSession, campaign_id: int) -> dict[str, int]:
    """Aggregate recipient counts without downloading the entire outbox."""
    result = await session.execute(
        select(
            ShopCampaignDelivery.status,
            func.count(ShopCampaignDelivery.id),
        )
        .where(ShopCampaignDelivery.campaign_id == campaign_id)
        .group_by(ShopCampaignDelivery.status)
    )
    return {status: int(count) for status, count in result.all()}


async def _business_media_ready(session: AsyncSession, campaign: ShopCampaign) -> int:
    """Fail before any paid send if this Bale bot lacks a required file ID."""
    from services.shop_bot_secrets import resolve_active_token

    bot = await _dispatch_bot(session, campaign)
    if bot.platform != "bale":
        raise CampaignRejected("بات بله مقصد آماده ارسال نیست.")
    bot_id = bot.id
    token = await session.run_sync(
        lambda sync: resolve_active_token(sync, bot_id=bot_id)
    )
    attachments = await ShopCampaignService._attachments(session, campaign)
    fingerprint = bot_fingerprint(token)
    from dashboard.media_storage import safe_media_path

    for attachment in attachments:
        path = safe_media_path(config.SHOP_MEDIA_ROOT, attachment.storage_key)
        selection = bale_media_method(
            attachment.kind, attachment.mime_type, path.stat().st_size
        )
        if selection.name not in (
            "sendPhoto",
            "sendVideo",
            "sendDocument",
            "sendAudio",
        ):
            raise CampaignRejected("این نوع فایل در Bale Business API قابل ارسال نیست.")
        cached = await cached_file_id(
            platform="bale",
            bot_key=fingerprint,
            bot_id=bot_id,
            storage_key=attachment.storage_key,
            kind=selection.kind,
        )
        if not cached:
            raise CampaignRejected(
                "فایل هنوز برای بازوی بله آماده نیست. ابتدا "
                "file_id را در چت خصوصی مدیر آماده کنید."
            )
    return len(attachments)


async def _dispatch_bot(
    session: AsyncSession,
    campaign: ShopCampaign,
) -> ShopBot:
    """Require a ready receiver and the exact registered campaign owner."""
    if not campaign.bot_id:
        raise CampaignRejected("بات مقصد کمپین را انتخاب کنید.")
    if not registry_dispatch_enabled():
        raise CampaignRejected("ارسال کمپین این بات هنوز فعال نشده است.")
    bot = await session.scalar(ready_registry_bot(
        bot_id=campaign.bot_id, store_id=campaign.store_id,
    ))
    if bot is None or campaign.audience not in ("all", bot.platform):
        raise CampaignRejected("بات یا فروشگاه مقصد آماده ارسال نیست.")
    return bot


class BroadcastControl:
    """Strict state transitions for background-running marketing campaigns."""

    @staticmethod
    async def start(
        session: AsyncSession,
        *,
        campaign_id: int,
        actor: str,
        bale_mode: str = "standard",
        approved_paid_calls: int = 0,
    ) -> int:
        """Start one approved campaign with a frozen verified paid-call cap.

        Business mode must be explicitly enabled and the manager must confirm
        the exact worst-case number of paid API messages before the first send.
        """
        if not (
            config.SHOP_CAMPAIGN_DISPATCH_ENABLED
            and config.SHOP_BROADCAST_WORKER_ENABLED
        ):
            raise CampaignRejected(
                "Worker و ارسال کمپین تا پایان تست عملیاتی غیرفعال‌اند."
            )
        if type(approved_paid_calls) is not int or approved_paid_calls < 0:
            raise CampaignRejected("سقف درخواست‌های هزینه‌دار معتبر نیست.")
        campaign = await session.scalar(
            select(ShopCampaign).where(ShopCampaign.id == campaign_id).with_for_update()
        )
        if campaign is None or campaign.status != "approved":
            raise CampaignRejected("کمپین باید قبلاً تأیید شده باشد.")
        require_campaign_scope(campaign)
        bot = await _dispatch_bot(session, campaign)
        if bale_mode not in ("standard", "business"):
            raise CampaignRejected("روش ارسال بله معتبر نیست.")
        attachments = await ShopCampaignService._attachments(session, campaign)
        counts = await delivery_counts(session, campaign.id)
        if not counts.get("queued"):
            raise CampaignRejected("گیرنده‌ای برای ارسال وجود ندارد.")

        result = await session.execute(
            select(
                ShopIdentity.platform,
                func.count(ShopCampaignDelivery.id),
            )
            .join(
                ShopCampaignDelivery,
                ShopCampaignDelivery.identity_id == ShopIdentity.id,
            )
            .where(
                ShopCampaignDelivery.campaign_id == campaign.id,
                ShopCampaignDelivery.status == "queued",
            )
            .group_by(ShopIdentity.platform)
        )
        recipients = {platform: int(total) for platform, total in result.all()}
        mismatched = await session.scalar(
            select(func.count())
            .select_from(ShopCampaignDelivery)
            .join(ShopIdentity, ShopIdentity.id == ShopCampaignDelivery.identity_id)
            .where(
                ShopCampaignDelivery.campaign_id == campaign.id,
                ShopCampaignDelivery.status == "queued",
                (
                    ShopCampaignDelivery.bot_id.is_distinct_from(ShopIdentity.bot_id)
                    | (ShopIdentity.store_id != campaign.store_id)
                    | (
                        ShopIdentity.platform != campaign.audience
                        if campaign.audience != "all"
                        else false()
                    )
                    | (ShopIdentity.platform != bot.platform)
                    | (ShopIdentity.bot_id != campaign.bot_id)
                ),
            )
        )
        if mismatched:
            raise CampaignRejected("مالکیت گیرندگان کمپین با بات مجاز مطابقت ندارد.")
        if bale_mode == "business":
            if (
                not recipients.get("bale")
                or config.BALE_BROADCAST_MODE != "business"
                or not config.BALE_BROADCAST_PAID_ENABLED
            ):
                raise CampaignRejected(
                    "Bale Business API به تأیید و فعال‌سازی صریح نیاز دارد."
                )
            # Every recipient gets one text and all configured attachments.
            required = recipients["bale"] * (1 + len(attachments))
            if (
                required <= 0
                or approved_paid_calls != required
                or required > config.SHOP_BROADCAST_MAX_PAID_CALLS
            ):
                raise CampaignRejected(
                    f"برای Business API دقیقاً سقف {required} درخواست "
                    "و محدودیت مجاز فروشگاه را تأیید کنید."
                )
            await _business_media_ready(session, campaign)
            budget = required
        else:
            if approved_paid_calls != 0:
                raise CampaignRejected(
                    "در حالت عادی، سقف ارسال هزینه‌دار باید صفر باشد."
                )
            budget = 0

        previous = campaign.status
        campaign.bale_mode = bale_mode
        campaign.max_paid_calls = budget
        campaign.paid_calls_reserved = 0
        campaign.started_at = datetime.now(UTC)
        campaign.paused_at = None
        campaign.last_error_code = None
        campaign.status = "sending"
        record_audit(
            session,
            campaign_id=campaign.id,
            actor=actor,
            action="start",
            old_status=previous,
            new_status=campaign.status,
            reason=(f"Bale mode={bale_mode}; approved paid calls={budget}"),
        )
        await session.commit()
        return counts["queued"]

    @staticmethod
    async def change(
        session: AsyncSession,
        *,
        campaign_id: int,
        actor: str,
        action: str,
    ) -> None:
        """Pause, resume or cancel with a predictable per-recipient boundary."""
        campaign = await session.scalar(
            select(ShopCampaign).where(ShopCampaign.id == campaign_id).with_for_update()
        )
        if campaign is None:
            raise CampaignRejected("کمپین یافت نشد.")
        require_campaign_scope(campaign)
        previous = campaign.status
        now = datetime.now(UTC)
        if action == "pause" and previous == "sending":
            campaign.status = "paused"
            campaign.paused_at = now
        elif action == "resume" and previous == "paused":
            if not (
                config.SHOP_CAMPAIGN_DISPATCH_ENABLED
                and config.SHOP_BROADCAST_WORKER_ENABLED
            ):
                raise CampaignRejected("ارسال یا Worker غیرفعال است.")
            if (
                campaign.bale_mode == "business"
                and not config.BALE_BROADCAST_PAID_ENABLED
            ):
                raise CampaignRejected("مجوز Business API بله غیرفعال است.")
            await _dispatch_bot(session, campaign)
            counts = await delivery_counts(session, campaign.id)
            if counts.get("queued", 0) <= 0:
                raise CampaignRejected("گیرنده صف‌شده‌ای باقی نمانده است.")
            if campaign.bale_mode == "business":
                await _business_media_ready(session, campaign)
            campaign.status = "sending"
            campaign.paused_at = None
            campaign.last_error_code = None
        elif action == "cancel" and previous in (
            "approved",
            "sending",
            "paused",
            "needs_review",
        ):
            campaign.status = "cancelled"
            campaign.finished_at = now
            # A currently in-flight recipient is not forcibly retried or
            # rolled back. Mark only unsent queued recipients as skipped.
            await session.execute(
                update(ShopCampaignDelivery)
                .where(
                    ShopCampaignDelivery.campaign_id == campaign.id,
                    ShopCampaignDelivery.status == "queued",
                )
                .values(status="skipped", last_error_code="cancelled")
            )
        else:
            raise CampaignRejected("این انتقال وضعیت کمپین مجاز نیست.")
        record_audit(
            session,
            campaign_id=campaign.id,
            actor=actor,
            action=action,
            old_status=previous,
            new_status=campaign.status,
        )
        await session.commit()

    @staticmethod
    async def reconcile(
        session: AsyncSession,
        *,
        campaign_id: int,
        delivery_id: int,
        actor: str,
        resolution: str,
        evidence: str,
    ) -> None:
        """Resolve an uncertain delivery after checking provider evidence.

        A resolution never requeues the recipient. Sending again requires
        an entirely new, separately approved campaign.
        """
        if (
            resolution not in ("sent", "skipped")
            or not 12 <= len(evidence.strip()) <= 255
        ):
            raise CampaignRejected("مدرک بررسی تحویل یا تصمیم نامعتبر است.")
        campaign = await session.scalar(
            select(ShopCampaign).where(ShopCampaign.id == campaign_id).with_for_update()
        )
        if campaign is not None:
            require_campaign_scope(campaign)
        delivery = await session.scalar(
            select(ShopCampaignDelivery)
            .where(
                ShopCampaignDelivery.id == delivery_id,
                ShopCampaignDelivery.campaign_id == campaign_id,
            )
            .with_for_update()
        )
        if campaign is None or delivery is None or delivery.status != "unknown":
            raise CampaignRejected("گیرنده نیازمند بررسی یافت نشد.")
        old = delivery.status
        delivery.status = resolution
        if resolution == "sent":
            delivery.sent_at = datetime.now(UTC)
        delivery.last_error_code = "reconciled_by_operator"
        record_audit(
            session,
            campaign_id=campaign_id,
            delivery_id=delivery.id,
            actor=actor,
            action="reconcile",
            old_status=old,
            new_status=resolution,
            reason=evidence.strip(),
        )
        counts = await delivery_counts(session, campaign.id)
        if (
            campaign.status in ("needs_review", "paused")
            and not counts.get("unknown")
            and not counts.get("queued")
            and not counts.get("sending")
        ):
            old_campaign = campaign.status
            campaign.status = "completed"
            campaign.finished_at = datetime.now(UTC)
            record_audit(
                session,
                campaign_id=campaign.id,
                actor=actor,
                action="finish",
                old_status=old_campaign,
                new_status="completed",
            )
        await session.commit()
