"""Authenticated SQLAdmin uploader for product files and testimonials."""

from __future__ import annotations

import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqladmin import BaseView, expose
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, RedirectResponse

import config
from dashboard.media_storage import (
    UnsupportedMediaError,
    safe_media_path,
    save_media,
)
from db import session_maker
from models.shop_content import Product, ProductMedia, Testimonial


class ShopUploadView(BaseView):
    """Supply a protected upload form within the existing SQLAdmin interface."""

    name = "بارگذاری رسانه"
    icon = "fa-solid fa-cloud-arrow-up"
    category = "محتوا"

    @staticmethod
    async def _products() -> list[Product]:
        """Return editable products for the upload form."""
        async with session_maker() as session:
            result = await session.execute(
                select(Product).order_by(Product.position, Product.id)
            )
            return list(result.scalars().all())

    @expose("/media-upload", methods=["GET", "POST"])
    async def media_upload(self, request: Request):
        """Validate CSRF, file and product before committing metadata."""
        if request.method == "GET":
            csrf = secrets.token_urlsafe(32)
            request.session["shop_upload_csrf"] = csrf
            return await self.templates.TemplateResponse(
                request,
                "shop/media-upload.html",
                context={
                    "products": await self._products(),
                    "csrf": csrf,
                    "error": None,
                    "notice": request.query_params.get("status") == "saved",
                    "max_megabytes": config.SHOP_MEDIA_MAX_BYTES // 1024 // 1024,
                },
            )

        form = await request.form(max_files=1, max_fields=15)
        csrf = form.get("csrf")
        stored_csrf = request.session.get("shop_upload_csrf")
        if not (
            isinstance(csrf, str)
            and isinstance(stored_csrf, str)
            and secrets.compare_digest(csrf, stored_csrf)
        ):
            raise HTTPException(status_code=403, detail="درخواست تأیید نشد.")
        # Single use per form prevents accidental repeated submissions.
        request.session.pop("shop_upload_csrf", None)
        file = form.get("file")
        stored = None
        try:
            product_id = int(form.get("product_id", "0"))
            position = int(form.get("position", "0"))
            if product_id < 1 or not 0 <= position <= 1000000:
                raise ValueError("اطلاعات محصول یا ترتیب نادرست است.")
            target = form.get("target")
            if target not in ("media", "testimonial"):
                raise ValueError("نوع محتوا معتبر نیست.")
            caption = str(form.get("caption") or "").strip()
            if len(caption) > 2000:
                raise ValueError("متن توضیح بیش از حد طولانی است.")
            uploaded = file if isinstance(file, UploadFile) and file.filename else None
            if target == "media" and uploaded is None:
                raise ValueError("برای رسانه محصول باید فایل انتخاب شود.")
            if uploaded is None and not caption:
                raise ValueError("برای رضایت مشتری متن یا فایل لازم است.")

            async with session_maker() as session:
                if await session.get(Product, product_id) is None:
                    raise ValueError("محصول مورد نظر یافت نشد.")
                if uploaded is not None:
                    stored = await save_media(
                        uploaded,
                        root=config.SHOP_MEDIA_ROOT,
                        max_bytes=config.SHOP_MEDIA_MAX_BYTES,
                    )
                if target == "media":
                    item = ProductMedia(
                        product_id=product_id,
                        storage_key=stored.key,
                        original_filename=stored.original_filename,
                        mime_type=stored.mime_type,
                        size_bytes=stored.size_bytes,
                        kind=stored.kind,
                        caption=caption or None,
                        position=position,
                        is_published=False,
                    )
                else:
                    item = Testimonial(
                        product_id=product_id,
                        text=caption or None,
                        media_storage_key=stored.key if stored else None,
                        media_kind=stored.kind if stored else None,
                        media_mime_type=stored.mime_type if stored else None,
                        position=position,
                        is_approved=False,
                    )
                session.add(item)
                await session.commit()
            return RedirectResponse(
                url="/admin/media-upload?status=saved", status_code=303
            )
        except (ValueError, UnsupportedMediaError, SQLAlchemyError) as exc:
            if stored is not None:
                safe_media_path(config.SHOP_MEDIA_ROOT, stored.key).unlink(
                    missing_ok=True
                )
            message = (
                "ذخیره در پایگاه داده انجام نشد."
                if isinstance(exc, SQLAlchemyError)
                else str(exc)
            )
            csrf = secrets.token_urlsafe(32)
            request.session["shop_upload_csrf"] = csrf
            return await self.templates.TemplateResponse(
                request,
                "shop/media-upload.html",
                context={
                    "products": await self._products(),
                    "csrf": csrf,
                    "error": message,
                    "notice": False,
                    "max_megabytes": config.SHOP_MEDIA_MAX_BYTES // 1024 // 1024,
                },
                status_code=400,
            )

    @expose("/media-preview/{kind}/{record_id}", methods=["GET"])
    async def media_preview(self, request: Request):
        """Serve only previously validated media to authenticated admins."""
        kind = request.path_params["kind"]
        try:
            record_id = int(request.path_params["record_id"])
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found") from None
        async with session_maker() as session:
            if kind == "product":
                item = await session.get(ProductMedia, record_id)
                if item is None:
                    raise HTTPException(status_code=404, detail="Not found")
                key, mime = item.storage_key, item.mime_type
            elif kind == "testimonial":
                item = await session.get(Testimonial, record_id)
                if item is None or item.media_storage_key is None:
                    raise HTTPException(status_code=404, detail="Not found")
                key, mime = item.media_storage_key, item.media_mime_type
            else:
                raise HTTPException(status_code=404, detail="Not found")

        path = safe_media_path(config.SHOP_MEDIA_ROOT, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        inline = mime in {
            "image/png", "image/jpeg", "image/webp", "image/gif",
            "application/pdf", "video/mp4", "audio/mpeg", "audio/ogg",
        }
        return FileResponse(
            path=path,
            media_type=mime or "application/octet-stream",
            content_disposition_type="inline" if inline else "attachment",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
            },
        )
