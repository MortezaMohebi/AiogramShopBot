"""A shared read-only catalog flow used by both messaging adapters.

Menu structure is deliberately static. Products and testimonial content come
from the database, are filtered by publication status, and are never fixtures.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction, Platform
from models.shop_content import Product, Testimonial

_PAGE_SIZE = 6
_REVIEW_PAGE_SIZE = 3
_LIST_PATTERN = re.compile(r"shop:list:(0|[1-9][0-9]{0,8})\Z")
_PRODUCT_PATTERN = re.compile(r"shop:item:([1-9][0-9]{0,8})\Z")
_REVIEW_PATTERN = re.compile(r"shop:reviews:([1-9][0-9]{0,8}):(0|[1-9][0-9]{0,8})\Z")


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

    def __init__(self, currency_label: str = "ریال") -> None:
        """Provide an explicit display currency, never convert stored prices."""
        self.currency_label = currency_label

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve recognized commands or buttons; ignore other bot features."""
        if event.callback_data is not None:
            data = event.callback_data
            match = _LIST_PATTERN.fullmatch(data)
            if match:
                return await self._list_products(session, int(match.group(1)))
            match = _PRODUCT_PATTERN.fullmatch(data)
            if match:
                return await self._product(session, int(match.group(1)))
            match = _REVIEW_PATTERN.fullmatch(data)
            if match:
                return await self._reviews(
                    session, int(match.group(1)), int(match.group(2))
                )
            if data.startswith("shop:"):
                return BotReply(
                    "درخواست معتبر نیست. لطفاً دوباره از فهرست محصولات شروع کنید.",
                    ((_button("🛍 محصولات", "shop:list:0"),),),
                )
            return None

        text = (event.text or "").strip()
        if text in ("/catalog", "محصولات", "🛍 محصولات", "🏠 صفحه اول"):
            return await self._list_products(session, 0)
        if event.platform == Platform.BALE and text.split(" ", 1)[0] == "/start":
            return await self._list_products(session, 0)
        return None

    async def _list_products(
        self, session: AsyncSession, requested_page: int
    ) -> BotReply:
        """Render a bounded page of published products."""
        condition = Product.is_published.is_(True)
        count_result = await session.execute(
            select(func.count()).select_from(Product).where(condition)
        )
        count = count_result.scalar_one()
        if count == 0:
            return BotReply("هنوز محصولی برای نمایش منتشر نشده است.")

        last_page = (count - 1) // _PAGE_SIZE
        page = min(requested_page, last_page)
        results = await session.execute(
            select(Product)
            .where(condition)
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
        if page > 0:
            controls.append(_button("صفحه قبل", f"shop:list:{page - 1}"))
        if page < last_page:
            controls.append(_button("صفحه بعد", f"shop:list:{page + 1}"))
        if controls:
            rows.append(tuple(controls))

        return BotReply(
            text=f"🛍 محصولات فروشگاه\nصفحه {page + 1} از {last_page + 1}",
            rows=tuple(rows),
        )

    async def _product(self, session: AsyncSession, product_id: int) -> BotReply:
        """Show an active product, never exposing an unpublished record."""
        result = await session.execute(
            select(Product).where(
                Product.id == product_id,
                Product.is_published.is_(True),
            )
        )
        product = result.scalar_one_or_none()
        if product is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", "shop:list:0"),),),
            )

        stock = (
            f"موجودی: {product.stock_quantity}"
            if product.stock_quantity > 0
            else "ناموجود"
        )
        description = product.description[:2800]
        if len(product.description) > 2800:
            description += "…"
        body = (
            f"{product.name}\n\n{description}\n\n"
            f"قیمت: {_price(product.price)} {self.currency_label}\n{stock}"
        )
        return BotReply(
            text=body,
            rows=(
                (_button("💬 رضایت مشتریان", f"shop:reviews:{product.id}:0"),),
                (_button("بازگشت به محصولات", "shop:list:0"),),
            ),
        )

    async def _reviews(
        self, session: AsyncSession, product_id: int, requested_page: int
    ) -> BotReply:
        """Show approved text testimonials for one published product."""
        exists = await session.execute(
            select(Product.id).where(
                Product.id == product_id, Product.is_published.is_(True)
            )
        )
        if exists.scalar_one_or_none() is None:
            return BotReply(
                "این محصول در حال حاضر قابل نمایش نیست.",
                ((_button("بازگشت به محصولات", "shop:list:0"),),),
            )

        condition = (
            Testimonial.product_id == product_id,
            Testimonial.is_approved.is_(True),
            Testimonial.text.is_not(None),
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
            f"• {item.text[:900]}{'…' if len(item.text) > 900 else ''}"
            for item in testimonials
        ]
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
        )
