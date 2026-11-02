"""Marketing-only administration of durable Telegram/Bale campaigns.

The admin never sends batches in the HTTP request. It approves a frozen
recipient outbox, explicitly starts the independent worker, and may pause,
resume, cancel or reconcile uncertain external messages with audit evidence.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

import config
from channels.bale import BaleTransport
from dashboard.permissions import require_role
from db import session_maker
from models.shop_content import ShopIdentity
from models.shop_engagement import (
    ShopBroadcastWorkerHeartbeat, ShopCampaign, ShopCampaignDelivery,
    ShopCampaignMedia,
)
from services.shop_broadcast_control import BroadcastControl
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class ShopCampaignReviewView(BaseView):
    """Manage the durable outbox without synchronous end-user message sends."""

    name = "ارسال اطلاعیه"
    category = "بازاریابی"
    icon = "fa-solid fa-bullhorn"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Show controls to authorized marketing staff only."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "marketing"
        )

    @expose("/campaign-review", methods=["GET", "POST"])
    async def campaign_review(self, request: Request):
        """Render live DB progress or change a specific campaign state."""
        require_role(request, "marketing")
        if request.method == "POST":
            return await self._perform(request)

        nonce = secrets.token_urlsafe(32)
        request.session["shop_campaign_csrf"] = nonce
        async with session_maker() as session:
            result = await session.execute(
                select(ShopCampaign)
                .order_by(ShopCampaign.id.desc())
                .limit(50)
            )
            campaigns = result.scalars().all()
            campaign_ids = [campaign.id for campaign in campaigns]
            counts: dict[int, dict[str, int]] = {}
            bale_counts: dict[int, int] = {}
            media_counts: dict[int, int] = {}
            unresolved: dict[int, list] = {}

            if campaign_ids:
                groups = await session.execute(
                    select(
                        ShopCampaignDelivery.campaign_id,
                        ShopCampaignDelivery.status,
                        func.count(),
                    )
                    .where(
                        ShopCampaignDelivery.campaign_id.in_(campaign_ids)
                    )
                    .group_by(
                        ShopCampaignDelivery.campaign_id,
                        ShopCampaignDelivery.status,
                    )
                )
                for campaign_id, state, count in groups.all():
                    counts.setdefault(campaign_id, {})[state] = int(count)

                bale = await session.execute(
                    select(
                        ShopCampaignDelivery.campaign_id, func.count()
                    )
                    .join(
                        ShopIdentity,
                        ShopIdentity.id == ShopCampaignDelivery.identity_id,
                    )
                    .where(
                        ShopCampaignDelivery.campaign_id.in_(campaign_ids),
                        ShopIdentity.platform == "bale",
                    )
                    .group_by(ShopCampaignDelivery.campaign_id)
                )
                bale_counts = {
                    campaign_id: int(n) for campaign_id, n in bale.all()
                }
                media = await session.execute(
                    select(
                        ShopCampaignMedia.campaign_id, func.count()
                    )
                    .where(ShopCampaignMedia.campaign_id.in_(campaign_ids))
                    .group_by(ShopCampaignMedia.campaign_id)
                )
                media_counts = {
                    campaign_id: int(n) for campaign_id, n in media.all()
                }

                # Display a bounded list of unresolved recipients, not all
                # private IDs in the outbox for large broadcasts.
                pending_review = await session.execute(
                    select(ShopCampaignDelivery, ShopIdentity)
                    .join(
                        ShopIdentity,
                        ShopIdentity.id == ShopCampaignDelivery.identity_id,
                    )
                    .where(
                        ShopCampaignDelivery.campaign_id.in_(campaign_ids),
                        ShopCampaignDelivery.status == "unknown",
                    )
                    .order_by(ShopCampaignDelivery.id.desc())
                    .limit(50)
                )
                for delivery, identity in pending_review.all():
                    unresolved.setdefault(delivery.campaign_id, []).append(
                        (delivery, identity)
                    )

            last_heartbeat = await session.scalar(
                select(func.max(ShopBroadcastWorkerHeartbeat.last_seen_at))
            )
        if last_heartbeat is not None and last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
        online = (
            last_heartbeat is not None
            and last_heartbeat >= (
                datetime.now(timezone.utc) - timedelta(seconds=60)
            )
        )
        estimate = {
            campaign.id: bale_counts.get(campaign.id, 0)
            * (1 + media_counts.get(campaign.id, 0))
            for campaign in campaigns
        }
        return await self.templates.TemplateResponse(
            request,
            "shop/campaign-review.html",
            context={
                "campaigns": campaigns,
                "counts": counts,
                "estimate": estimate,
                "unresolved": unresolved,
                "nonce": nonce,
                "result": request.query_params.get("result"),
                "worker_online": online,
                "worker_enabled": (
                    config.SHOP_BROADCAST_WORKER_ENABLED
                    and config.SHOP_CAMPAIGN_DISPATCH_ENABLED
                ),
                "bale_paid_enabled": (
                    config.BALE_BROADCAST_PAID_ENABLED
                    and config.BALE_BROADCAST_MODE == "business"
                ),
                "bale_paid_cap": config.SHOP_BROADCAST_MAX_PAID_CALLS,
                "bale_prepare_ready": bool(
                    config.BALE_BOT_TOKEN
                    and config.BALE_BROADCAST_PREPARE_CHAT_ID > 0
                ),
            },
        )

    async def _perform(self, request: Request) -> RedirectResponse:
        """Handle one CSRF-protected lifecycle decision and nothing else."""
        form = await request.form(max_fields=12, max_files=0)
        supplied = form.get("nonce")
        saved = request.session.pop("shop_campaign_csrf", None)
        if not (
            isinstance(supplied, str)
            and isinstance(saved, str)
            and secrets.compare_digest(supplied, saved)
        ):
            raise HTTPException(status_code=403, detail="فرم تأیید نشد.")
        action = form.get("action")
        confirmation = form.get("confirmation")
        expected = {
            "approve": "APPROVE_CAMPAIGN",
            "prepare": "PREPARE_BALE_MEDIA",
            "pause": "PAUSE_CAMPAIGN",
            "resume": "RESUME_CAMPAIGN",
            "cancel": "CANCEL_CAMPAIGN",
            "reconcile": "RECONCILE_DELIVERY",
        }
        if action == "start":
            expected["start"] = (
                "START_PAID_BALE"
                if form.get("bale_mode") == "business"
                else "START_CAMPAIGN"
            )
        if expected.get(action) != confirmation:
            raise HTTPException(
                status_code=400, detail="عبارت تأیید عملیات معتبر نیست."
            )
        try:
            campaign_id = int(form.get("campaign_id"))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail="شناسه کمپین معتبر نیست."
            ) from None
        if campaign_id <= 0:
            raise HTTPException(status_code=400, detail="شناسه نامعتبر است.")
        staff_id = getattr(request.state, "shop_staff_id", None)
        if type(staff_id) is not int:
            raise HTTPException(status_code=403, detail="مجوز معتبر نیست.")
        actor = f"staff:{staff_id}"

        async with session_maker() as session:
            try:
                if action == "approve":
                    await ShopCampaignService.approve(
                        session, campaign_id=campaign_id, approver=actor
                    )
                elif action == "prepare":
                    await self._prepare_bale_media(
                        session, campaign_id=campaign_id
                    )
                elif action == "start":
                    try:
                        paid_calls = int(form.get("max_paid_calls") or "0")
                    except (TypeError, ValueError):
                        raise CampaignRejected(
                            "سقف هزینه پیام‌های بله نامعتبر است."
                        ) from None
                    await BroadcastControl.start(
                        session, campaign_id=campaign_id, actor=actor,
                        bale_mode=str(form.get("bale_mode") or ""),
                        approved_paid_calls=paid_calls,
                    )
                elif action in ("pause", "resume", "cancel"):
                    await BroadcastControl.change(
                        session, campaign_id=campaign_id,
                        actor=actor, action=action,
                    )
                elif action == "reconcile":
                    try:
                        delivery_id = int(form.get("delivery_id") or "0")
                    except (TypeError, ValueError):
                        raise CampaignRejected(
                            "شناسه دریافت‌کننده معتبر نیست."
                        ) from None
                    await BroadcastControl.reconcile(
                        session,
                        campaign_id=campaign_id,
                        delivery_id=delivery_id,
                        actor=actor,
                        resolution=str(form.get("resolution") or ""),
                        evidence=str(form.get("evidence") or ""),
                    )
            except CampaignRejected as error:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail=str(error)
                ) from None
        return RedirectResponse(
            "/admin/campaign-review?result=" + action,
            status_code=303,
        )

    async def _prepare_bale_media(
        self, session, *, campaign_id: int
    ) -> None:
        """Upload each original to a private admin chat, never to recipients."""
        if (
            not config.BALE_BOT_TOKEN
            or config.BALE_BROADCAST_PREPARE_CHAT_ID <= 0
        ):
            raise CampaignRejected(
                "ابتدا توکن بازو و شناسه چت آماده‌سازی را ثبت کنید."
            )
        campaign = await session.get(ShopCampaign, campaign_id)
        if campaign is None or campaign.status not in (
            "draft", "approved"
        ):
            raise CampaignRejected(
                "آماده‌سازی فایل فقط برای کمپین پیش‌نویس یا تأییدشده مجاز است."
            )
        attachments = await ShopCampaignService._attachments(
            session, campaign
        )
        if not attachments:
            raise CampaignRejected("این کمپین فایل رسانه‌ای ندارد.")
        regular = BaleTransport(
            config.BALE_BOT_TOKEN,
            self._admin_ref.app.state.bale_http_client,
        )
        for attachment in attachments:
            await regular.send_media(
                config.BALE_BROADCAST_PREPARE_CHAT_ID, attachment
            )
