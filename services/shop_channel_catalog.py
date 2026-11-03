"""A shared read-only catalog flow used by both messaging adapters.

Menu structure is deliberately static. Products and testimonial content come
from the database, are filtered by publication status, and are never fixtures.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import (
    BotReply, InboundEvent, InlineAction, MediaAttachment, Platform,
)
from models.shop_content import (
    Product, ProductMedia, ShopCategory, ShopSettings, Testimonial,
)
from services.shop_money import format_rials
from models.shop_product_visibility import ShopProductVisibility
from services.shop_presentation import product_message
from services.shop_channel_features import get_features
from services.shop_bot_catalog_acl import (
    CatalogScope, legacy_bot_id, permitted_product_clause, resolve_scope,
)
from services.shop_bot_context import BotContext
from services.shop_admin_security import SecurityRejected
from models.shop_multibot import LEGACY_BOT_IDS
from models.shop_bot_operations import ShopBotOperations

_PAGE_SIZE = 6
_CATEGORY_PAGE_SIZE = 6
_REVIEW_PAGE_SIZE = 3
_MEDIA_PAGE_SIZE = 4
_LIST_PATTERN = re.compile(r"shop:list:(0|[1-9][0-9]{0,18})\Z")
_CATEGORY_PATTERN = re.compile(r"shop:category:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")
_CATEGORY_LIST_PATTERN = re.compile(r"shop:categories:(0|[1-9][0-9]{0,18})\Z")
_PRODUCT_PATTERN = re.compile(r"shop:item:([1-9][0-9]{0,18})\Z")
_REVIEW_PATTERN = re.compile(r"shop:reviews:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")
_MEDIA_PATTERN = re.compile(r"shop:files:([1-9][0-9]{0,18}):(0|[1-9][0-9]{0,18})\Z")


def _price(value: Decimal) -> str:
    """Format a Decimal without floating-point conversion."""
    formatted = format(value, ",.2f")
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _button(label: str, payload: str) -> InlineAction:
    """Limit product labels so inline buttons fit both APIs."""
    short_label = label if len(label) <= 64 else f"{label[:63]}…"
    return InlineAction(label=short_label, callback_data=payload)


class CatalogFlow:
    """Resolve catalog and review navigation using one shared SQL schema."""

    def __init__(
        self, currency_label: str = "ریال", display_unit: str = "IRR",
        *, bot_context: BotContext | None = None,
    ) -> None:
        """Bind optional trusted BotContext without a client-supplied bot ID."""
        self.currency_label = currency_label
        self.display_unit = display_unit
        # Future receivers supply only contexts resolved after authentication.
        self.bot_context = bot_context

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve recognized commands or buttons; ignore other bot features."""
        if self.bot_context is not None and (
            self.bot_context.platform != event.platform
        ):
            raise SecurityRejected("bot_identity_mismatch", 403)
        scope = await resolve_scope(
            session, bot_id=(
                self.bot_context.bot_id if self.bot_context
                else legacy_bot_id(event.platform.value)
            ),
        )
        if event.callback_data is not None:
            data = event.callback_data
            match = _LIST_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(session, int(match.group(1)), scope=scope)
            match = _CATEGORY_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(
                    session, int(match.group(2)), category_id=int(match.group(1)), scope=scope
                )
            match = _PRODUCT_PATTERN.fullmatch(data)
            if match:
                return await self._product(session, int(match.group(1)), event.platform.value, scope)
            match = _REVIEW_PATTERN.fullmatch(data)
            if match:
                return await self._reviews(
                    session, int(match.group(1)), int(match.group(2)), scope
                )
            match = _MEDIA_PATTERN.fullmatch(data)
            if match:
                return await self._media(
                    session, int(match.group(1)), int(match.group(2)), scope
                )
            if data == "shop:home":
                return await self._home(session, event.platform.value)
            if data == "shop:help":
                return await self._settings_text(session, key="support", platform=event.platform.value)
            if data == "shop:faq":
                return await self._settings_text(session, key="faq", platform=event.platform.value)
            match = _CATEGORY_LIST_PATTERN.fullmatch(data)
            if match:
                return await self._categories_or_products(
                    session, requested_page=int(match.group(1)), scope=scope
                )
            if data == "shop:categories":
                return await self._categories_or_products(session, scope=scope)
            if data.startswith("shop:"):
                return BotReply(
                    "درخواست معتبر نیست. لطفاً دوباره از فهرست محصولات شروع کنید.",
                    ((_button("🛍 محصولات", "shop:list:0"),),),
                )
            return None

        text = (event.text or "").strip()
        if text in ("/catalog", "محصولات", "🛍 محصولات", "🏠 صفحه اول"):
            return await self._categories_or_products(session, scope=scope)
        if text.split(" ", 1)[0] == "/start":
            return await self._home(session, event.platform.value)
        if text in ("/help", "پشتیبانی", "🆘 پشتیبانی"):
            return await self._settings_text(session, key="support", platform=event.platform.value)
        if text in ("❓ پرسش‌های متداول", "/faq"):
            return await self._settings_text(session, key="faq", platform=event.platform.value)
        return None

    async def _home(self, session: AsyncSession, platform: str) -> BotReply:
        """Build a small fixed menu, with all business copy from settings."""
        settings = await session.get(ShopSettings, 1)
        per_bot = await session.get(ShopBotOperations, LEGACY_BOT_IDS[platform])
        welcome = (
            per_bot.welcome_message
            if per_bot and per_bot.welcome_message
            else settings.welcome_message
            if settings and settings.welcome_message
            else "به فروشگاه خوش آمدید."
        )
        features = await get_features(session, platform)
        rows = [
            (_button("🛍 محصولات", "shop:categories"),),
            (_button("📦 سفارش‌های من", "shop:orders"),),
        ]
        if features.cart_enabled:
            rows.append((_button("🛒 سبد خرید", "shop:cart"),))
        rows.extend([
            (_button("🆘 پشتیبانی", "shop:help"),),
            (_button("❓ پرسش‌های متداول", "shop:faq"),),
        ])
        return BotReply(text=welcome[:4096], rows=tuple(rows))

    async def _settings_text(
        self, session: AsyncSession, *, key: str, platform: str
    ) -> BotReply:
        """Read help and support information from editable admin settings."""
        settings = await session.get(ShopSettings, 1)
        per_bot = await session.get(ShopBotOperations, LEGACY_BOT_IDS[platform])
        if key == "faq":
            body = settings.faq_text if settings else None
        else:
            url = (per_bot.support_url or "").strip() if per_bot and per_bot.support_url else ((settings.support_url or "").strip() if settings else "")
            body = url if url.startswith("https://") else None
        return BotReply(
            text=(body or "اطلاعات این بخش هنوز ثبت نشده است.")[:4096],
            rows=((_button("🏠 صفحه اول", "shop:home"),),),
        )

    async def _categories_or_products(
        self, session: AsyncSession, requested_page: int = 0,
        *, scope: CatalogScope,
    ) -> BotReply:
        """Paginate an unlimited number of administrator-created categories."""
        category_has_permitted_product = select(Product.id).where(
            Product.category_id == ShopCategory.id,
            permitted_product_clause(scope),
        ).correlate(ShopCategory).exists()
        condition = (
            ShopCategory.is_published.is_(True)
            & category_has_permitted_product
        )
        count = await session.scalar(
            select(func.count()).select_from(ShopCategory).where(condition)
        )
        if not count:
            return await self._list_products(session, 0, scope=scope)
        last_page = (count - 1) // _CATEGORY_PAGE_SIZE
        page = min(requested_page, last_page)
        result = await session.execute(
            select(ShopCategory)
            .where(condition)
            .order_by(ShopCategory.position, ShopCategory.id)
            .offset(page * _CATEGORY_PAGE_SIZE)
            .limit(_CATEGORY_PAGE_SIZE)
        )
        rows = [
            (_button(item.name, f"shop:category:{item.id}:0"),)
            for item in result.scalars().all()
        ]
        controls = []
        if page:
            controls.append(
                _button("صفحه قبل", f"shop:categories:{page - 1}")
            )
        if page < last_page:
            controls.append(
                _button("صفحه بعد", f"shop:categories:{page + 1}")
            )
        if controls:
            rows.append(tuple(controls))
        rows.append((_button("همه محصولات", "shop:list:0"),))
        return BotReply(
            text=(
                "🗂️ دسته‌بندی محصولات را انتخاب کنید:\n"
                f"صفحه {page + 1} از {last_page + 1}"
            ),
            rows=tuple(rows),
        )

    async def _list_products(
        self,
        session: AsyncSession,
        requested_page: int,
        category_id: int | None = None,
        *, scope: CatalogScope,
    ) -> BotReply:
        """Render a bounded page of published products."""
        filters = [permitted_product_clause(scope)]
        if category_id is not None:
            selected = await session.scalar(
                select(ShopCategory.id).where(
                    ShopCategory.id == category_id,
                    ShopCategory.is_published.is_(True),
                )
            )
            if selected is None:
                return BotReply("این دسته‌بندی قابل نمایش نیست.")
            filters.append(Product.category_id == category_id)
        count_result = await session.execute(
            select(func.count()).select_from(Product).where(*filters)
        )
        count = count_result.scalar_one()
        if count == 0:
            return BotReply("هنوز محصولی برای نمایش منتشر نشده است.")

        last_page = (count - 1) // _PAGE_SIZE
        page = min(requested_page, last_page)
        results = await session.execute(
            select(Product)
            .where(*filters)
            .order_by(Product.position, Product.id)
            .offset(page * _PAGE_SIZE)
            .limit(_PAGE_SIZE)
        )
        products = results.scalars().all()
        rows = [
            (_button(product.name, f"shop:item:{product.id}"),)
            for product in products
        ]
        controls = []
        prefix = (
            f"shop:category:{category_id}" if category_id is not None
            else "shop:list"
        )
        if page > 0:
            controls.append(_button("صفحه قبل", f"{prefix}:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"{prefix}:{page + 1}"))
        if controls:
            rows.append(tuple(controls))
        rows.append((_button("🗂️ دسته‌بندی‌ها", "shop:categories"),))

        return BotReply(
            text=f"🛍 محصولات فروشگاه\nصفحه {page + 1} از {last_page + 1}",
            rows=tuple(rows),
        )

    async def _product(
        self, session: AsyncSession, product_id: int,
        platform: str, scope: CatalogScope,
    ) -> BotReply:
        """Show an active product, never exposing an unpublished record."""
        result = await session.execute(
            select(Product).where(
                Product.id == product_id,
                permitted_product_clause(scope),
            )
        )
        product = result.scalar_one_or_none()
        if product is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", "shop:list:0"),),),
            )

        visibility = await session.get(ShopProductVisibility, product.id)
        show_description = visibility.show_description if visibility else True
        show_stock = visibility.show_stock if visibility else True
        show_media = visibility.show_media if visibility else True
        show_reviews = visibility.show_reviews if visibility else True
        body = product_message(
            product,
            price_label=format_rials(product.price, self.display_unit),
            show_description=show_description,
            show_stock=show_stock,
        )
        features = await get_features(session, platform)
        rows = []
        if features.cart_enabled:
            if product.stock_quantity > 0:
                rows.append(
                    (_button("🛒 افزودن به سبد", f"shop:add:{product.id}"),)
                )
            rows.append((_button("🛒 مشاهده سبد", "shop:cart"),))
        rows.append((_button("📦 سفارش‌های من", "shop:orders"),))
        # Hide the navigation controls as well as the underlying data.
        if show_media:
            rows.append((_button("📎 تصاویر و فایل‌ها", f"shop:files:{product.id}:0"),))
        if show_reviews:
            rows.append((_button("💬 رضایت مشتریان", f"shop:reviews:{product.id}:0"),))
        rows.append((_button("بازگشت به محصولات", "shop:list:0"),))
        return BotReply(text=body, rows=tuple(rows))

    async def _media(
        self, session: AsyncSession, product_id: int,
        requested_page: int, scope: CatalogScope,
    ) -> BotReply:
        """Page through unlimited published product media without hardcoding files."""
        published = await session.scalar(
            select(Product.id).where(
                Product.id == product_id, permitted_product_clause(scope)
            )
        )
        if published is None:
            return BotReply("این محصول در حال حاضر قابل نمایش نیست.")
        policy = await session.get(ShopProductVisibility, product_id)
        if policy is not None and not policy.show_media:
            return BotReply("رسانه‌های این محصول برای نمایش فعال نیستند.")
        condition = (
            ProductMedia.product_id == product_id,
            ProductMedia.is_published.is_(True),
        )
        result = await session.execute(
            select(func.count()).select_from(ProductMedia).where(*condition)
        )
        count = result.scalar_one()
        if count == 0:
            return BotReply(
                "هنوز فایلی برای این محصول منتشر نشده است.",
                ((_button("بازگشت", f"shop:item:{product_id}"),),),
            )
        last_page = (count - 1) // _MEDIA_PAGE_SIZE
        page = min(requested_page, last_page)
        items = await session.execute(
            select(ProductMedia)
            .where(*condition)
            .order_by(ProductMedia.position, ProductMedia.id)
            .offset(page * _MEDIA_PAGE_SIZE)
            .limit(_MEDIA_PAGE_SIZE)
        )
        attachments = tuple(
            MediaAttachment(
                storage_key=item.storage_key,
                kind=item.kind,
                mime_type=item.mime_type,
                caption=item.caption or "",
            )
            for item in items.scalars().all()
        )
        controls = []
        if page:
            controls.append(_button("صفحه قبل", f"shop:files:{product_id}:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"shop:files:{product_id}:{page + 1}"))
        rows = [tuple(controls)] if controls else []
        rows.append((_button("بازگشت به محصول", f"shop:item:{product_id}"),))
        return BotReply(
            text=f"📎 فایل‌های محصول\nصفحه {page + 1} از {last_page + 1}",
            rows=tuple(rows),
            attachments=attachments,
        )

    async def _reviews(
        self, session: AsyncSession, product_id: int,
        requested_page: int, scope: CatalogScope,
    ) -> BotReply:
        """Show approved text testimonials for one published product."""
        exists = await session.execute(
            select(Product.id).where(
                Product.id == product_id, permitted_product_clause(scope)
            )
        )
        if exists.scalar_one_or_none() is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", "shop:list:0"),),),
            )
        policy = await session.get(ShopProductVisibility, product_id)
        if policy is not None and not policy.show_reviews:
            return BotReply("رضایت‌های این محصول برای نمایش فعال نیستند.")

        condition = (
            Testimonial.product_id == product_id,
            Testimonial.is_approved.is_(True),
        )
        count_result = await session.execute(
            select(func.count()).select_from(Testimonial).where(*condition)
        )
        count = count_result.scalar_one()
        if not count:
            return BotReply(
                "هنوز رضایت متنی تأییدشده‌ای برای این محصول وجود ندارد.",
                ((_button("بازگشت به محصول", f"shop:item:{product_id}"),),),
            )

        last_page = (count - 1) // _REVIEW_PAGE_SIZE
        page = min(requested_page, last_page)
        result = await session.execute(
            select(Testimonial)
            .where(*condition)
            .order_by(Testimonial.position, Testimonial.id)
            .offset(page * _REVIEW_PAGE_SIZE)
            .limit(_REVIEW_PAGE_SIZE)
        )
        testimonials = result.scalars().all()
        snippets = [
            f"• {(item.text or 'رضایت تصویری/صوتی')[:600]}"
            for item in testimonials
        ]
        attachments = tuple(
            MediaAttachment(
                storage_key=item.media_storage_key,
                kind=item.media_kind or "document",
                mime_type=item.media_mime_type or "application/octet-stream",
                caption=(item.text or "")[:900],
            )
            for item in testimonials
            if item.media_storage_key
        )
        controls = []
        if page > 0:
            controls.append(
                _button("صفحه قبل", f"shop:reviews:{product_id}:{page - 1}")
            )
        if page < last_page:
            controls.append(
                _button("صفحه بعد", f"shop:reviews:{product_id}:{page + 1}")
            )
        rows = []
        if controls:
            rows.append(tuple(controls))
        rows.append((_button("بازگشت به محصول", f"shop:item:{product_id}"),))
        return BotReply(
            text="💬 رضایت مشتریان\n\n" + "\n\n".join(snippets),
            rows=tuple(rows),
            attachments=attachments,
        )
