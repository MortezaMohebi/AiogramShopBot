"""Marketing-only media attachment uploader for draft broadcast campaigns.

An approved campaign is immutable: uploaded files cannot change the content
after recipients have been snapshotted for delivery.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqladmin import BaseView, expose
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse

import config
from dashboard.media_storage import (
    UnsupportedMediaError, safe_media_path, save_media,
)
from dashboard.permissions import require_role
from db import session_maker
from models.shop_engagement import ShopCampaign, ShopCampaignMedia


class ShopCampaignMediaUploadView(BaseView):
    """Upload files for a broadcast only while that broadcast is a draft."""

    name = "بارگذاری فایل کمپین"
    category = "بازاریابی"
    icon = "fa-solid fa-file-arrow-up"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Allow Marketing or Superadmin to open the campaign upload form."""
        return getattr(request.state, "shop_role", None) in (
            "superadmin", "marketing"
        )

    @staticmethod
    async def _drafts() -> list[ShopCampaign]:
        """Load real editable campaigns rather than hardcoded content."""
        async with session_maker() as session:
            result = await session.execute(
                select(ShopCampaign)
                .where(ShopCampaign.status == "draft")
                .order_by(ShopCampaign.id.desc()).limit(100)
            )
            return list(result.scalars().all())

    @expose("/campaign-media-upload", methods=["GET", "POST"])
    async def campaign_media_upload(self, request: Request):
        """Validate operator, CSRF, draft status and private file signatures."""
        require_role(request, "marketing")
        if request.method == "GET":
            nonce = secrets.token_urlsafe(32)
            request.session["campaign_media_csrf"] = nonce
            return await self.templates.TemplateResponse(
                request, "shop/campaign-media-upload.html",
                context={
                    "nonce": nonce,
                    "campaigns": await self._drafts(),
                    "saved": request.query_params.get("status") == "saved",
                    "error": None,
                },
            )

        form = await request.form(max_files=1, max_fields=8)
        nonce = form.get("nonce")
        saved = request.session.pop("campaign_media_csrf", None)
        if not (
            isinstance(nonce, str) and isinstance(saved, str)
            and secrets.compare_digest(nonce, saved)
        ):
            raise HTTPException(status_code=403, detail="فرم معتبر نیست.")
        uploaded = form.get("file")
        stored = None
        try:
            campaign_id = int(form.get("campaign_id", "0"))
            position = int(form.get("position", "0"))
            caption = str(form.get("caption") or "").strip()
            if campaign_id < 1 or not 0 <= position <= 1000000:
                raise ValueError("کمپین یا ترتیب فایل معتبر نیست.")
            if len(caption) > 1024:
                raise ValueError("توضیح رسانه حداکثر ۱۰۲۴ نویسه است.")
            if not isinstance(uploaded, UploadFile) or not uploaded.filename:
                raise ValueError("برای افزودن رسانه باید فایل انتخاب کنید.")

            async with session_maker() as session:
                campaign = await session.scalar(
                    select(ShopCampaign).where(
                        ShopCampaign.id == campaign_id
                    ).with_for_update()
                )
                if campaign is None or campaign.status != "draft":
                    raise ValueError(
                        "فقط به کمپین پیش‌نویس می‌توان فایل اضافه کرد."
                    )
                stored = await save_media(
                    uploaded,
                    root=config.SHOP_MEDIA_ROOT,
                    max_bytes=config.SHOP_MEDIA_MAX_BYTES,
                )
                session.add(
                    ShopCampaignMedia(
                        campaign_id=campaign.id,
                        storage_key=stored.key,
                        original_filename=stored.original_filename,
                        kind=stored.kind,
                        mime_type=stored.mime_type,
                        size_bytes=stored.size_bytes,
                        caption=caption or None,
                        position=position,
                    )
                )
                await session.commit()
            return RedirectResponse(
                "/admin/campaign-media-upload?status=saved", status_code=303
            )
        except (ValueError, UnsupportedMediaError, SQLAlchemyError) as exc:
            if stored is not None:
                safe_media_path(config.SHOP_MEDIA_ROOT, stored.key).unlink(
                    missing_ok=True
                )
            nonce = secrets.token_urlsafe(32)
            request.session["campaign_media_csrf"] = nonce
            return await self.templates.TemplateResponse(
                request, "shop/campaign-media-upload.html",
                context={
                    "nonce": nonce,
                    "campaigns": await self._drafts(),
                    "saved": False,
                    "error": (
                        "خطا در ذخیره پایگاه داده."
                        if isinstance(exc, SQLAlchemyError) else str(exc)
                    ),
                },
                status_code=400,
            )


class ShopCampaignMediaPreviewView(BaseView):
    """Serve campaign originals to authorized marketing staff only."""

    name = "پیش‌نمایش فایل کمپین"
    category = "بازاریابی"

    @staticmethod
    def is_visible(request: Request) -> bool:
        """Do not expose a parameterized preview path in the sidebar."""
        return False

    @expose("/campaign-media-preview/{media_id}", methods=["GET"])
    async def campaign_media_preview(self, request: Request):
        """Return a private, uncached preview with sandboxed content."""
        require_role(request, "marketing")
        try:
            media_id = int(request.path_params["media_id"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=404, detail="Not found") from None
        async with session_maker() as session:
            media = await session.get(ShopCampaignMedia, media_id)
            if media is None:
                raise HTTPException(status_code=404, detail="Not found")
            key, mime = media.storage_key, media.mime_type
        path = safe_media_path(config.SHOP_MEDIA_ROOT, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(
            path,
            media_type=mime,
            content_disposition_type="inline",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Security-Policy": "sandbox",
                "X-Content-Type-Options": "nosniff",
            },
        )
