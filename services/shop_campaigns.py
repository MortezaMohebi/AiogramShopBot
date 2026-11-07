"""Validate campaign media and snapshot explicit marketing consent.

All actual sends run only through the durable shared BroadcastWorker, which
enforces global/per-chat pacing and prevents ambiguous retries.
"""

from __future__ import annotations

from sqlalchemy import func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.contracts import MediaAttachment
from channels.media_policy import MediaLimitError, bale_media_method
from dashboard.media_storage import safe_media_path
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopCampaign,
    ShopCampaignDelivery,
    ShopCampaignMedia,
)
from models.shop_multibot import ShopBot, ShopStore
from services.shop_customer_access import customer_access_clause


class CampaignRejected(ValueError):
    """Campaign approval or dispatch failed without silently resending."""


def require_campaign_scope(campaign: ShopCampaign) -> None:
    """Enforce the current trusted Store even for already-loaded ORM rows."""
    from services.shop_store_context import current_context

    scope = current_context()
    if scope is not None:
        scope.require(campaign.store_id, write=True)


class ShopCampaignService:
    """Prepare opted-in recipients without sending any Bot API message."""

    @staticmethod
    async def _attachments(
        session: AsyncSession,
        campaign: ShopCampaign,
    ) -> tuple[MediaAttachment, ...]:
        """Load and validate actual private originals before a campaign send."""
        result = await session.execute(
            select(ShopCampaignMedia)
            .where(ShopCampaignMedia.campaign_id == campaign.id)
            .order_by(ShopCampaignMedia.position, ShopCampaignMedia.id)
        )
        attachments = []
        for item in result.scalars().all():
            path = safe_media_path(config.SHOP_MEDIA_ROOT, item.storage_key)
            try:
                actual_bytes = path.stat().st_size
            except OSError:
                raise CampaignRejected(
                    "یکی از فایل‌های کمپین از فضای خصوصی حذف شده است."
                ) from None
            if actual_bytes != item.size_bytes:
                raise CampaignRejected(
                    "حجم فایل کمپین تغییر کرده؛ قبل از ارسال بررسی کنید."
                )
            try:
                # The shop uses the stricter Bale caps even for an
                # all-platform broadcast, so both channels can deliver it.
                bale_media_method(item.kind, item.mime_type, actual_bytes)
            except MediaLimitError as error:
                raise CampaignRejected(str(error)) from None
            attachments.append(
                MediaAttachment(
                    storage_key=item.storage_key,
                    kind=item.kind,
                    mime_type=item.mime_type,
                    caption=item.caption or "",
                )
            )
        return tuple(attachments)

    @staticmethod
    async def approve(session: AsyncSession, *, campaign_id: int, approver: str) -> int:
        """Materialize recipients only after explicit marketing approval."""
        if type(campaign_id) is not int or campaign_id <= 0:
            raise CampaignRejected("شناسه کمپین نامعتبر است.")
        if not 1 <= len(approver) <= 120:
            raise CampaignRejected("شناسه تأییدکننده معتبر نیست.")
        campaign = await session.scalar(
            select(ShopCampaign).where(ShopCampaign.id == campaign_id).with_for_update()
        )
        if campaign is None or campaign.status != "draft":
            raise CampaignRejected("کمپین قابل تأیید نیست.")
        require_campaign_scope(campaign)
        if not 1 <= len(campaign.title) <= 120:
            raise CampaignRejected("عنوان کمپین معتبر نیست.")
        if not 1 <= len(campaign.text) <= 3000:
            raise CampaignRejected("متن اطلاعیه باید حداکثر ۳۰۰۰ نویسه باشد.")
        if campaign.audience not in ("all", "telegram", "bale"):
            raise CampaignRejected("کانال ارسال معتبر نیست.")
        await ShopCampaignService._attachments(session, campaign)

        clause = [
            # INSERT SELECT bypasses ORM write hooks; scope it explicitly.
            ShopIdentity.store_id == campaign.store_id,
            ShopIdentity.allow_announcements.is_(True),
            customer_access_clause(),
        ]
        if not campaign.bot_id:
            raise CampaignRejected("بات مقصد کمپین را انتخاب کنید.")
        bot = await session.get(ShopBot, campaign.bot_id)
        if (
            bot is None
            or bot.runtime_owner != "registry"
            or bot.status != "active"
            or bot.store_id != campaign.store_id
            or campaign.audience not in ("all", bot.platform)
        ):
            raise CampaignRejected("بات مقصد فعال نیست یا کانال کمپین نامعتبر است.")
        store = await session.get(ShopStore, bot.store_id)
        if store is None or store.state != "active":
            raise CampaignRejected("فروشگاه مقصد فعال نیست.")
        clause.extend(
            (
                ShopIdentity.bot_id == bot.id,
                ShopIdentity.platform == bot.platform,
            )
        )
        if campaign.audience != "all":
            clause.append(ShopIdentity.platform == campaign.audience)
        stmt = insert(ShopCampaignDelivery).from_select(
            ["campaign_id", "identity_id", "bot_id", "status"],
            select(
                literal(campaign.id),
                ShopIdentity.id,
                ShopIdentity.bot_id,
                literal("queued"),
            ).where(*clause),
        )
        await session.execute(stmt)
        count = await session.scalar(
            select(func.count())
            .select_from(ShopCampaignDelivery)
            .where(ShopCampaignDelivery.campaign_id == campaign.id)
        )
        campaign.approved_by = approver
        campaign.status = "approved" if count else "completed"
        await session.commit()
        return count
