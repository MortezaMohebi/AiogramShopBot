"""One-consent-per-recipient marketing outbox for Telegram and Bale.

Campaign send is a bounded, manager-triggered action. Dispatch states are
persisted before sending; a timeout never triggers a blind duplicate retry.
No background worker or automatic campaign schedule is hidden in this module.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import func, insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_content import ShopIdentity
from models.shop_engagement import ShopCampaign, ShopCampaignDelivery


SendMessage = Callable[[Platform, int, str], Awaitable[None]]
_MAX_PER_BATCH = 10


class CampaignRejected(ValueError):
    """Campaign approval or dispatch failed without silently resending."""


class ShopCampaignService:
    """Prepare opted-in recipients and dispatch no more than ten per action."""

    @staticmethod
    async def approve(
        session: AsyncSession, *, campaign_id: int, approver: str
    ) -> int:
        """Materialize recipients only after explicit marketing approval."""
        if type(campaign_id) is not int or campaign_id <= 0:
            raise CampaignRejected("شناسه کمپین نامعتبر است.")
        if not 1 <= len(approver) <= 120:
            raise CampaignRejected("شناسه تأییدکننده معتبر نیست.")
        campaign = await session.scalar(
            select(ShopCampaign).where(
                ShopCampaign.id == campaign_id
            ).with_for_update()
        )
        if campaign is None or campaign.status != "draft":
            raise CampaignRejected("کمپین قابل تأیید نیست.")
        if not 1 <= len(campaign.title) <= 120:
            raise CampaignRejected("عنوان کمپین معتبر نیست.")
        if not 1 <= len(campaign.text) <= 3000:
            raise CampaignRejected("متن اطلاعیه باید حداکثر ۳۰۰۰ نویسه باشد.")
        if campaign.audience not in ("all", "telegram", "bale"):
            raise CampaignRejected("کانال ارسال معتبر نیست.")

        clause = [
            ShopIdentity.allow_announcements.is_(True),
            ShopIdentity.is_blocked.is_(False),
        ]
        if campaign.audience != "all":
            clause.append(
                ShopIdentity.platform == campaign.audience
            )
        stmt = insert(ShopCampaignDelivery).from_select(
            ["campaign_id", "identity_id", "status"],
            select(
                literal(campaign.id),
                ShopIdentity.id,
                literal("queued"),
            ).where(*clause)
        )
        await session.execute(stmt)
        count = await session.scalar(
            select(func.count()).select_from(ShopCampaignDelivery).where(
                ShopCampaignDelivery.campaign_id == campaign.id
            )
        )
        campaign.approved_by = approver
        campaign.status = "approved" if count else "completed"
        await session.commit()
        return count

    @staticmethod
    async def dispatch_batch(
        session: AsyncSession,
        *,
        campaign_id: int,
        send: SendMessage,
    ) -> tuple[int, int]:
        """Send a bounded batch of queued notifications at most once.

        Requests in status `sending` or `unknown` require manual
        reconciliation after a network failure, not automatic retries.
        """
        campaign = await session.scalar(
            select(ShopCampaign).where(
                ShopCampaign.id == campaign_id
            )
        )
        if campaign is None or campaign.status not in (
            "approved", "sending"
        ):
            raise CampaignRejected("کمپین برای ارسال آماده نیست.")
        results = await session.execute(
            select(ShopCampaignDelivery, ShopIdentity)
            .join(
                ShopIdentity,
                ShopIdentity.id == ShopCampaignDelivery.identity_id,
            )
            .where(
                ShopCampaignDelivery.campaign_id == campaign_id,
                ShopCampaignDelivery.status == "queued",
            )
            .order_by(ShopCampaignDelivery.id)
            .limit(_MAX_PER_BATCH)
            .with_for_update(of=ShopCampaignDelivery, skip_locked=True)
        )
        candidates = results.all()
        successes, skipped = 0, 0
        for delivery, identity in candidates:
            # Recheck consent after a prepared recipient opts out.
            if identity.is_blocked or not identity.allow_announcements:
                delivery.status = "skipped"
                skipped += 1
                await session.commit()
                continue
            delivery.status = "sending"
            campaign.status = "sending"
            await session.commit()

            try:
                await send(
                    Platform(identity.platform),
                    identity.platform_user_id,
                    campaign.text,
                )
            except Exception:
                # The Bot API may have already delivered the message. Do
                # NOT retry without consulting an operator and provider.
                delivery.status = "unknown"
                await session.commit()
            else:
                delivery.status = "sent"
                delivery.sent_at = datetime.now(timezone.utc)
                successes += 1
                await session.commit()

        unresolved = await session.scalar(
            select(func.count()).select_from(ShopCampaignDelivery).where(
                ShopCampaignDelivery.campaign_id == campaign_id,
                ShopCampaignDelivery.status.in_(
                    ("queued", "sending", "unknown")
                ),
            )
        )
        if unresolved == 0:
            campaign.status = "completed"
            await session.commit()
        return successes, skipped
