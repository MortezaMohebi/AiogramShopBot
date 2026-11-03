"""Durable broadcast campaign lifecycle and explicit paid-Bale approvals.

Only this service may transition a campaign into or out of background sending.
A manager approves recipients and a frozen cost ceiling before start; the
worker, not the web request, sends every queued recipient.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import false, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.media_policy import bale_media_method
from models.shop_content import ShopIdentity
from models.shop_multibot import LEGACY_BOT_IDS
from models.shop_engagement import (
    ShopCampaign, ShopCampaignAudit, ShopCampaignDelivery,
)
from services.shop_campaigns import CampaignRejected, ShopCampaignService
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


async def delivery_counts(
    session: AsyncSession, campaign_id: int
) -> dict[str, int]:
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


async def _business_media_ready(
    session: AsyncSession, campaign: ShopCampaign
) -> int:
    """Fail before any paid send if this Bale bot lacks a required file ID."""
    if not config.BALE_BOT_TOKEN:
        raise CampaignRejected("توکن بله تنظیم نشده است.")
    attachments = await ShopCampaignService._attachments(session, campaign)
    fingerprint = bot_fingerprint(config.BALE_BOT_TOKEN)
    from dashboard.media_storage import safe_media_path

    for attachment in attachments:
        path = safe_media_path(
            config.SHOP_MEDIA_ROOT, attachment.storage_key
        )
        selection = bale_media_method(
            attachment.kind, attachment.mime_type, path.stat().st_size
        )
        if selection.name not in (
            "sendPhoto", "sendVideo", "sendDocument", "sendAudio"
        ):
            raise CampaignRejected(
                "این نوع فایل در Bale Business API قابل ارسال نیست."
            )
        cached = await cached_file_id(
            platform="bale", bot_key=fingerprint,
            storage_key=attachment.storage_key, kind=selection.kind,
        )
        if not cached:
            raise CampaignRejected(
                "فایل هنوز برای بازوی بله آماده نیست. ابتدا "
                "file_id را در چت خصوصی مدیر آماده کنید."
            )
    return len(attachments)


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
            select(ShopCampaign).where(
                ShopCampaign.id == campaign_id
            ).with_for_update()
        )
        if campaign is None or campaign.status != "approved":
            raise CampaignRejected("کمپین باید قبلاً تأیید شده باشد.")
        # Only the original two tokens are available to the existing worker.
        # Do not launch a registry-owned campaign using an unrelated token.
        if (
            campaign.bot_id is not None
            and campaign.bot_id not in LEGACY_BOT_IDS.values()
        ):
            raise CampaignRejected(
                "ارسال Broadcast این بات تا فعال شدن Worker اختصاصی آن "
                "مجاز نیست؛ گیرندگان و مجوزها محفوظ می‌مانند."
            )
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
        # An old campaign can legitimately address both legacy bots, but
        # every recipient must still own the matching delivery ledger row.
        mismatched = await session.scalar(
            select(func.count()).select_from(ShopCampaignDelivery)
            .join(ShopIdentity, ShopIdentity.id == ShopCampaignDelivery.identity_id)
            .where(
                ShopCampaignDelivery.campaign_id == campaign.id,
                ShopCampaignDelivery.status == "queued",
                (
                    (ShopCampaignDelivery.bot_id != ShopIdentity.bot_id)
                    | ShopIdentity.bot_id.not_in(tuple(LEGACY_BOT_IDS.values()))
                    | (
                        ShopIdentity.bot_id != campaign.bot_id
                        if campaign.bot_id is not None else false()
                    )
                ),
            )
        )
        if mismatched:
            raise CampaignRejected(
                "مالکیت گیرندگان کمپین با بات مجاز مطابقت ندارد."
            )
        if recipients.get("telegram") and not config.TOKEN:
            raise CampaignRejected("اتصال تلگرام پیکربندی نشده است.")
        if recipients.get("bale") and not config.BALE_BOT_TOKEN:
            raise CampaignRejected("اتصال بله پیکربندی نشده است.")

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
        campaign.started_at = datetime.now(timezone.utc)
        campaign.paused_at = None
        campaign.last_error_code = None
        campaign.status = "sending"
        record_audit(
            session, campaign_id=campaign.id, actor=actor,
            action="start", old_status=previous, new_status=campaign.status,
            reason=(
                f"Bale mode={bale_mode}; approved paid calls={budget}"
            ),
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
            select(ShopCampaign).where(
                ShopCampaign.id == campaign_id
            ).with_for_update()
        )
        if campaign is None:
            raise CampaignRejected("کمپین یافت نشد.")
        previous = campaign.status
        now = datetime.now(timezone.utc)
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
            counts = await delivery_counts(session, campaign.id)
            if counts.get("queued", 0) <= 0:
                raise CampaignRejected("گیرنده صف‌شده‌ای باقی نمانده است.")
            if campaign.bale_mode == "business":
                await _business_media_ready(session, campaign)
            campaign.status = "sending"
            campaign.paused_at = None
            campaign.last_error_code = None
        elif action == "cancel" and previous in (
            "approved", "sending", "paused", "needs_review"
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
            session, campaign_id=campaign.id, actor=actor,
            action=action, old_status=previous, new_status=campaign.status,
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
            select(ShopCampaign).where(
                ShopCampaign.id == campaign_id
            ).with_for_update()
        )
        delivery = await session.scalar(
            select(ShopCampaignDelivery).where(
                ShopCampaignDelivery.id == delivery_id,
                ShopCampaignDelivery.campaign_id == campaign_id,
            ).with_for_update()
        )
        if campaign is None or delivery is None or delivery.status != "unknown":
            raise CampaignRejected("گیرنده نیازمند بررسی یافت نشد.")
        old = delivery.status
        delivery.status = resolution
        if resolution == "sent":
            delivery.sent_at = datetime.now(timezone.utc)
        delivery.last_error_code = "reconciled_by_operator"
        record_audit(
            session, campaign_id=campaign_id, delivery_id=delivery.id,
            actor=actor, action="reconcile", old_status=old,
            new_status=resolution, reason=evidence.strip(),
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
            campaign.finished_at = datetime.now(timezone.utc)
            record_audit(
                session, campaign_id=campaign.id, actor=actor,
                action="finish", old_status=old_campaign,
                new_status="completed",
            )
        await session.commit()
