"""Marketing-only campaign approval and bounded dispatch from SQLAdmin."""

from __future__ import annotations

import secrets

from sqlalchemy import func, select
from sqladmin import BaseView, expose
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse

import config
from channels.bale import BaleTransport
from channels.media_policy import bale_media_method
from services.shop_media_delivery import bot_fingerprint, cached_file_id
from dashboard.media_storage import safe_media_path
from channels.contracts import BotReply, MediaAttachment, Platform
from channels.telegram import TelegramTransport
from dashboard.permissions import require_role
from db import session_maker
from models.shop_content import ShopIdentity
from models.shop_engagement import ShopCampaign, ShopCampaignDelivery
from services.shop_campaigns import CampaignRejected, ShopCampaignService


class ShopCampaignReviewView(BaseView):
    """Manually approve consent-only campaigns and send small batches."""

    name = "ارسال اطلاعیه"
    category = "بازاریابی"
    icon = "fa-solid fa-bullhorn"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Display marketing actions only to marketing staff."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "marketing"
        )

    @expose("/campaign-review", methods=["GET", "POST"])
    async def campaign_review(self, request: Request):
        """Show current outbox or perform an explicit CSRF-checked action."""
        require_role(request, "marketing")
        if request.method == "POST":
            return await self._perform(request)

        nonce = secrets.token_urlsafe(32)
        request.session["shop_campaign_csrf"] = nonce
        async with session_maker() as session:
            result = await session.execute(
                select(ShopCampaign)
                .order_by(ShopCampaign.id.desc()).limit(50)
            )
            campaigns = result.scalars().all()
            ids = [row.id for row in campaigns]
            counts: dict[int, dict[str, int]] = {}
            if ids:
                result = await session.execute(
                    select(
                        ShopCampaignDelivery.campaign_id,
                        ShopCampaignDelivery.status,
                        func.count(),
                    )
                    .where(ShopCampaignDelivery.campaign_id.in_(ids))
                    .group_by(
                        ShopCampaignDelivery.campaign_id,
                        ShopCampaignDelivery.status,
                    )
                )
                for campaign_id, status, count in result.all():
                    counts.setdefault(campaign_id, {})[status] = count

        return await self.templates.TemplateResponse(
            request, "shop/campaign-review.html",
            context={
                "campaigns": campaigns,
                "counts": counts,
                "nonce": nonce,
                "result": request.query_params.get("result"),
                "business_mode": config.BALE_BROADCAST_MODE == "business",
            },
        )

    async def _perform(self, request: Request) -> RedirectResponse:
        """Approve or dispatch; no silent long-running background operation."""
        form = await request.form(max_fields=8, max_files=0)
        supplied = form.get("nonce")
        saved = request.session.pop("shop_campaign_csrf", None)
        if not (
            isinstance(supplied, str) and isinstance(saved, str)
            and secrets.compare_digest(supplied, saved)
        ):
            raise HTTPException(status_code=403, detail="فرم تأیید نشد.")
        action = form.get("action")
        confirmation = form.get("confirmation")
        if confirmation not in (
            "APPROVE_CAMPAIGN", "SEND_BATCH", "PREPARE_BALE_MEDIA"
        ):
            raise HTTPException(
                status_code=400, detail="تأیید صریح عملیات لازم است."
            )
        if (action, confirmation) not in (
            ("approve", "APPROVE_CAMPAIGN"),
            ("dispatch", "SEND_BATCH"),
            ("prepare", "PREPARE_BALE_MEDIA"),
        ):
            raise HTTPException(status_code=400, detail="عملیات معتبر نیست.")
        try:
            campaign_id = int(form.get("campaign_id"))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="شناسه معتبر نیست.") from None
        if campaign_id <= 0:
            raise HTTPException(status_code=400, detail="شناسه معتبر نیست.")
        staff_id = getattr(request.state, "shop_staff_id", None)
        if type(staff_id) is not int:
            raise HTTPException(status_code=403, detail="مجوز معتبر نیست.")

        async with session_maker() as session:
            try:
                if action == "approve":
                    await ShopCampaignService.approve(
                        session, campaign_id=campaign_id,
                        approver=f"staff:{staff_id}",
                    )
                elif action == "prepare":
                    if (
                        not config.BALE_BOT_TOKEN
                        or config.BALE_BROADCAST_PREPARE_CHAT_ID <= 0
                    ):
                        raise CampaignRejected(
                            "ابتدا شناسه چت آماده‌سازی و توکن بله را تنظیم کنید."
                        )
                    campaign = await session.get(ShopCampaign, campaign_id)
                    if campaign is None or campaign.status not in (
                        "draft", "approved"
                    ):
                        raise CampaignRejected(
                            "فقط کمپین پیش‌نویس/تأییدشده قابل آماده‌سازی است."
                        )
                    attachments = await ShopCampaignService._attachments(
                        session, campaign
                    )
                    if not attachments:
                        raise CampaignRejected("کمپین هیچ فایل رسانه‌ای ندارد.")
                    regular = BaleTransport(
                        config.BALE_BOT_TOKEN,
                        self._admin_ref.app.state.bale_http_client,
                    )
                    for attachment in attachments:
                        # Explicit operator action: uploads to the configured
                        # *private admin chat* through the regular free API.
                        await regular.send_media(
                            config.BALE_BROADCAST_PREPARE_CHAT_ID,
                            attachment,
                        )
                else:
                    if not config.SHOP_CAMPAIGN_DISPATCH_ENABLED:
                        raise CampaignRejected(
                            "ارسال کمپین تا پایان تست عملیاتی غیرفعال است."
                        )
                    if not config.BALE_BOT_TOKEN:
                        # Do not claim Bale deliveries if the adapter has not
                        # been configured in the final deployment phase.
                        has_bale = await session.scalar(
                            select(ShopCampaignDelivery.id)
                            .join(
                                ShopIdentity,
                                ShopIdentity.id ==
                                ShopCampaignDelivery.identity_id,
                            )
                            .where(
                                ShopCampaignDelivery.campaign_id == campaign_id,
                                ShopCampaignDelivery.status == "queued",
                                ShopIdentity.platform == "bale",
                            )
                            .limit(1)
                        )
                        if has_bale is not None:
                            raise CampaignRejected(
                                "ابتدا اتصال بله را پیکربندی کنید."
                            )

                    campaign = await session.get(ShopCampaign, campaign_id)
                    if campaign is None:
                        raise CampaignRejected("کمپین پیدا نشد.")
                    uses_bale = campaign.audience in ("all", "bale")
                    paid_bale = (
                        uses_bale and
                        config.BALE_BROADCAST_MODE == "business"
                    )
                    if paid_bale and not config.BALE_BROADCAST_PAID_ENABLED:
                        raise CampaignRejected(
                            "Business API بله هزینه‌دار است؛ فعال‌سازی صریح لازم است."
                        )
                    telegram = TelegramTransport(
                        self._admin_ref.app.state.telegram_bot
                    )
                    bale = (
                        BaleTransport(
                            config.BALE_BOT_TOKEN,
                            self._admin_ref.app.state.bale_http_client,
                            business_mode=paid_bale,
                        )
                        if config.BALE_BOT_TOKEN else None
                    )

                    async def media_preflight(
                        attachments: tuple[MediaAttachment, ...],
                    ) -> None:
                        """Refuse paid sends before any recipient if file IDs lack."""
                        if not paid_bale:
                            return
                        if not config.BALE_BOT_TOKEN:
                            raise CampaignRejected("توکن بازوی بله تنظیم نشده است.")
                        key = bot_fingerprint(config.BALE_BOT_TOKEN)
                        for attachment in attachments:
                            path = safe_media_path(
                                config.SHOP_MEDIA_ROOT, attachment.storage_key
                            )
                            method = bale_media_method(
                                attachment.kind,
                                attachment.mime_type,
                                path.stat().st_size,
                            )
                            if method.name not in (
                                "sendPhoto", "sendVideo",
                                "sendDocument", "sendAudio",
                            ):
                                raise CampaignRejected(
                                    "این نوع رسانه در Business API بله مجاز نیست."
                                )
                            file_id = await cached_file_id(
                                platform="bale", bot_key=key,
                                storage_key=attachment.storage_key,
                                kind=method.kind,
                            )
                            if not file_id:
                                raise CampaignRejected(
                                    "فایل کمپین هنوز برای Business API آماده نیست؛ "
                                    "ابتدا «آماده‌سازی رسانه بله» را اجرا کنید."
                                )

                    async def deliver(
                        platform: Platform, user_id: int, text: str
                    ) -> None:
                        """Deliver one plain-text opted-in notification."""
                        reply = BotReply(text)
                        if platform == Platform.TELEGRAM:
                            await telegram.send(user_id, reply)
                        elif platform == Platform.BALE and bale is not None:
                            await bale.send(user_id, reply)
                        else:
                            raise RuntimeError(
                                "The required campaign adapter is unavailable."
                            )

                    async def deliver_attachment(
                        platform: Platform,
                        user_id: int,
                        attachment: MediaAttachment,
                    ) -> None:
                        """Send one campaign file from the private media store."""
                        if platform == Platform.TELEGRAM:
                            await telegram.send_media(user_id, attachment)
                        elif platform == Platform.BALE and bale is not None:
                            await bale.send_media(user_id, attachment)
                        else:
                            raise RuntimeError(
                                "Broadcast media adapter is unavailable."
                            )

                    await ShopCampaignService.dispatch_batch(
                        session,
                        campaign_id=campaign_id,
                        send=deliver,
                        send_attachment=deliver_attachment,
                        media_preflight=media_preflight,
                    )
            except CampaignRejected as error:
                await session.rollback()
                raise HTTPException(
                    status_code=409, detail=str(error)
                ) from None
        return RedirectResponse(
            "/admin/campaign-review?result=" + action, status_code=303
        )
