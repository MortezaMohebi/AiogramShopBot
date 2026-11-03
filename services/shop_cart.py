"""Common multi-item shopping flow for Telegram and Bale.

Both channel handlers use this same service; it has no platform SDK types.
This phase creates review-only orders, never takes money or reserves stock.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction, Platform
from models.shop_checkout import (
    ShopCart, ShopCartInputSession, ShopCartItem, ShopCoupon,
    ShopOrderLine, ShopShippingMethod,
)
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_uom import ShopUom
from models.shop_multibot import DEFAULT_STORE_ID
from services.shop_store_commerce import policy_for
from services.shop_money import MAX_RIALS, format_rials, to_rials
from services.shop_channel_features import get_features
from services.shop_bot_catalog_acl import (
    allowed_for_bot, lock_bot_catalog_policy,
)
from services.shop_bot_context import BotContext
from models.shop_scope import legacy_id

_PRODUCT_ACTION = re.compile(r"shop:(add|inc|dec|remove):([1-9][0-9]{0,18})\Z")
_SHIPPING_ACTION = re.compile(r"shop:ship:([1-9][0-9]{0,18})\Z")
_PLACE_ACTION = re.compile(
    r"shop:place:([1-9][0-9]{0,18}):([1-9][0-9]{0,18})\Z"
)
_MAX_LINES = 20
_SHIPPING_PAGE_SIZE = 10
_SHIPPING_PAGE_ACTION = re.compile(r"shop:shipping:(0|[1-9][0-9]{0,8})\Z")


class CartRejected(ValueError):
    """Human-readable cart or checkout validation failure."""


@dataclass(frozen=True, slots=True)
class QuoteLine:
    """A validated live product row used in a cart quotation."""

    product: Product
    quantity: int
    line_total: int


@dataclass(frozen=True, slots=True)
class CartQuote:
    """Canonical integer-IRR calculation with no floating-point operations."""

    lines: tuple[QuoteLine, ...]
    subtotal: int
    discount: int
    shipping: int
    total: int
    shipping_required: bool
    shipping_label: str | None
    coupon_code: str | None


def button(text: str, action: str) -> InlineAction:
    """Build a platform-neutral inline keyboard action."""
    return InlineAction(text[:64], action)


def validate_coupon(coupon: ShopCoupon, subtotal: int) -> int:
    """Calculate a bounded product-only discount or reject an invalid coupon."""
    now = datetime.now(timezone.utc)
    expires = coupon.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not coupon.is_active or (expires is not None and expires <= now):
        raise CartRejected("کد تخفیف غیرفعال یا منقضی شده است.")
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise CartRejected("ظرفیت این کد تخفیف تکمیل شده است.")
    if subtotal < coupon.minimum_subtotal_irr:
        raise CartRejected("حداقل مبلغ خرید برای این کد تخفیف تأمین نشده است.")
    if coupon.discount_type == "percent":
        if not 1 <= coupon.value <= 100:
            raise CartRejected("درصد تخفیف نامعتبر است.")
        computed = subtotal * coupon.value // 100
    elif coupon.discount_type == "fixed":
        computed = to_rials(coupon.value)
    else:
        raise CartRejected("نوع کد تخفیف معتبر نیست.")
    # Native payment providers must not receive a zero-value invoice.
    return min(computed, max(0, subtotal - 1))


class ShopCartFlow:
    """Shared cart navigation, quote and nonpaying order request workflow."""

    def __init__(
        self, display_unit: str = "IRR",
        *, bot_context: BotContext | None = None,
    ) -> None:
        """Bind only a server-authenticated bot; never trust callback bot IDs."""
        self.display_unit = display_unit
        self.bot_context = bot_context

    def _bot_id(self, platform: Platform) -> str:
        """Resolve the immutable owner of the current shopping context."""
        if self.bot_context is None:
            return legacy_id(platform.value)
        if self.bot_context.platform != platform:
            raise CartRejected("هویت بات با درخواست مطابقت ندارد.")
        return self.bot_context.bot_id

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve supported shopping actions for the event's platform identity."""
        action = event.callback_data or ""
        text = (event.text or "").strip()
        # A disabled provider cart refuses both current and stale callback buttons.
        # Existing orders remain accessible through the separate order service.
        features = await get_features(
            session, event.platform.value,
            bot_id=self._bot_id(event.platform),
        )
        if not features.cart_enabled:
            cart_actions = {
                "shop:cart", "shop:shipping", "shop:clear_coupon",
                "shop:address", "shop:coupon", "shop:checkout",
            }
            prefixes = (
                "shop:add:", "shop:inc:", "shop:dec:", "shop:remove:",
                "shop:ship:", "shop:shipping:", "shop:place:",
            )
            if (
                action in cart_actions or action.startswith(prefixes)
                or text in ("/cart", "/checkout", "🛒 سبد خرید")
            ):
                return BotReply("سبد خرید این پیام‌رسان در حال حاضر غیرفعال است.")
            return None
        try:
            if action in ("shop:cart", "shop:shipping", "shop:clear_coupon"):
                if action == "shop:shipping":
                    return await self._shipping_choices(event, session)
                if action == "shop:clear_coupon":
                    return await self._clear_coupon(event, session)
                return await self._cart_reply(event, session)
            if action in ("shop:address", "shop:coupon"):
                return await self._request_input(event, session, action)
            if action == "shop:checkout":
                return await self._checkout_preview(event, session)
            match = _SHIPPING_PAGE_ACTION.fullmatch(action)
            if match:
                return await self._shipping_choices(
                    event, session, int(match.group(1))
                )
            match = _PRODUCT_ACTION.fullmatch(action)
            if match:
                return await self._change_item(
                    event, session, match.group(1), int(match.group(2))
                )
            match = _SHIPPING_ACTION.fullmatch(action)
            if match:
                return await self._select_shipping(
                    event, session, int(match.group(1))
                )
            match = _PLACE_ACTION.fullmatch(action)
            if match:
                return await self._place_order(
                    event, session, int(match.group(1)), int(match.group(2))
                )
            if text in ("/cart", "🛒 سبد خرید"):
                return await self._cart_reply(event, session)
            if text in ("/checkout",):
                return await self._checkout_preview(event, session)

            cart = await self._get_cart(event, session, create=False)
            if (
                cart is not None and text and not text.startswith("/")
                and await self._input_state(cart, event, session)
            ):
                return await self._accept_input(cart, text, session, event)
            return None
        except CartRejected as error:
            # No write on validation errors. DB session rolls back at exit.
            return BotReply(
                str(error), ((button("🛒 بازگشت به سبد", "shop:cart"),),)
            )

    async def _get_cart(
        self, event: InboundEvent, session: AsyncSession,
        *, create: bool = False, lock: bool = False,
    ) -> ShopCart | None:
        """Select a bot-private or verified Customer cart by Store policy."""
        if event.user_id <= 0 or event.chat_id <= 0:
            raise CartRejected("شناسه خریدار معتبر نیست.")
        owner = self._bot_id(event.platform)
        identity = await session.scalar(select(ShopIdentity).where(
            ShopIdentity.bot_id == owner,
            ShopIdentity.platform == event.platform.value,
            ShopIdentity.platform_user_id == event.user_id,
        ))
        store_id = (
            self.bot_context.store_id if self.bot_context
            else identity.store_id if identity else DEFAULT_STORE_ID
        )
        if identity is not None and identity.store_id != store_id:
            raise CartRejected("فروشگاه حساب با بات انتخاب‌شده مطابقت ندارد.")
        if self.bot_context and self.bot_context.runtime_owner == "registry":
            if identity is None or identity.customer_id is None:
                raise CartRejected("ابتدا /start را در همین بات اجرا کنید.")

        sharing = (
            identity is not None and identity.customer_id is not None
            and (await policy_for(session, store_id=store_id)).cart_scope
            == "customer"
        )
        if sharing:
            statement = select(ShopCart).where(
                ShopCart.store_id == store_id,
                ShopCart.customer_id == identity.customer_id,
                ShopCart.is_shared.is_(True),
            )
        else:
            statement = select(ShopCart).where(
                ShopCart.bot_id == owner,
                ShopCart.platform == event.platform.value,
                ShopCart.platform_user_id == event.user_id,
                ShopCart.is_shared.is_(False),
            )
        if lock:
            statement = statement.with_for_update()
        cart = await session.scalar(statement)
        if cart is None and create:
            # An already populated private cart is retained for a future
            # migration decision; no automatic merge or stock mutation.
            cart = ShopCart(
                store_id=store_id,
                customer_id=identity.customer_id if identity else None,
                is_shared=sharing,
                bot_id=owner, platform=event.platform.value,
                platform_user_id=event.user_id, chat_id=event.chat_id,
                revision=1,
            )
            try:
                async with session.begin_nested():
                    session.add(cart)
                    await session.flush()
            except IntegrityError:
                cart = await session.scalar(statement)
                if cart is None:
                    raise CartRejected(
                        "در حال حاضر امکان بازکردن سبد وجود ندارد."
                    ) from None
        return cart

    async def _input_state(
        self, cart: ShopCart, event: InboundEvent, session: AsyncSession,
    ) -> str | None:
        """Read per-bot forms even when the purchased items are shared."""
        if not cart.is_shared:
            return cart.awaiting_input
        return await session.scalar(select(
            ShopCartInputSession.awaiting_input,
        ).where(
            ShopCartInputSession.bot_id == self._bot_id(event.platform),
            ShopCartInputSession.platform_user_id == event.user_id,
            ShopCartInputSession.cart_id == cart.id,
        ))

    async def _existing_pending(
        self, session: AsyncSession, cart: ShopCart, event: InboundEvent,
    ) -> ShopOrder | None:
        """Prevent concurrent financial checkout across linked bot identities."""
        if cart.is_shared:
            condition = (
                ShopOrder.store_id == cart.store_id,
                ShopOrder.customer_id == cart.customer_id,
            )
        else:
            condition = (
                ShopOrder.bot_id == self._bot_id(event.platform),
                ShopOrder.platform == event.platform.value,
                ShopOrder.platform_user_id == event.user_id,
            )
        return await session.scalar(select(ShopOrder).where(
            *condition, ShopOrder.status == "pending_payment",
        ).order_by(ShopOrder.id.desc()).limit(1))

    async def _change_item(
        self, event: InboundEvent, session: AsyncSession,
        action: str, product_id: int
    ) -> BotReply:
        """Modify a cart line with quantity and stock limits."""
        cart = await self._get_cart(event, session, create=True, lock=True)
        if await self._existing_pending(session, cart, event) is not None:
            raise CartRejected("یک سفارش در انتظار بررسی دارید؛ ابتدا وضعیت آن مشخص شود.")
        result = await session.execute(
            select(ShopCartItem).where(
                ShopCartItem.cart_id == cart.id,
                ShopCartItem.product_id == product_id,
            ).with_for_update()
        )
        line = result.scalar_one_or_none()
        if action in ("remove", "dec") and line is None:
            raise CartRejected("این محصول در سبد خرید شما وجود ندارد.")
        if action == "remove" and line is not None:
            await session.delete(line)
        elif action == "dec" and line is not None:
            if line.quantity == 1:
                await session.delete(line)
            else:
                line.quantity -= 1
        elif action in ("add", "inc"):
            # Stale add/inc callbacks cannot bypass a newly denied product.
            if not await allowed_for_bot(
                session, self._bot_id(event.platform), [product_id],
            ):
                raise CartRejected("این کالا در این بات قابل خرید نیست.")
            product = await session.get(Product, product_id)
            if (
                product is None or not product.is_published
                or product.store_id != cart.store_id
            ):
                raise CartRejected("این کالا برای خرید موجود نیست.")
            current = line.quantity if line is not None else 0
            new_quantity = current + 1
            if new_quantity > 99 or product.stock_quantity < new_quantity:
                raise CartRejected("تعداد درخواستی از موجودی کالا بیشتر است.")
            if line is not None:
                line.quantity = new_quantity
            else:
                count = await session.scalar(
                    select(func.count()).select_from(ShopCartItem).where(
                        ShopCartItem.cart_id == cart.id
                    )
                )
                if count >= _MAX_LINES:
                    raise CartRejected("حداکثر تعداد محصولات متفاوت در سبد تکمیل است.")
                session.add(
                    ShopCartItem(
                        cart_id=cart.id,
                        product_id=product_id,
                        quantity=1,
                    )
                )
        elif action not in ("remove", "dec"):
            raise CartRejected("عملیات سبد خرید شناخته‌شده نیست.")
        cart.revision += 1
        await session.commit()
        return await self._cart_reply(event, session)

    async def _quote(
        self, cart: ShopCart, session: AsyncSession, *, bot_id: str | None = None,
    ) -> CartQuote:
        """Calculate current product prices and optional shipping and coupon."""
        result = await session.execute(
            select(ShopCartItem, Product)
            .join(Product, Product.id == ShopCartItem.product_id)
            .where(ShopCartItem.cart_id == cart.id)
            .order_by(ShopCartItem.id)
        )
        rows = result.all()
        if not rows:
            raise CartRejected("سبد خرید خالی است.")
        # All cart routes including checkout and place_order re-evaluate the
        # current entitlements. No price or customer-facing name is exposed
        # after a product has been removed from this bot's catalog.
        if any(product.store_id != cart.store_id for _, product in rows):
            raise CartRejected("کالای سبد به فروشگاه دیگری تعلق دارد.")
        if not await allowed_for_bot(
            session, bot_id or cart.bot_id, [product.id for _, product in rows],
        ):
            raise CartRejected("یک یا چند کالای سبد دیگر در این بات مجاز نیستند.")
        lines: list[QuoteLine] = []
        subtotal = 0
        needs_shipping = False
        for cart_line, product in rows:
            if not product.is_published or product.stock_quantity < cart_line.quantity:
                raise CartRejected(f"موجودی «{product.name}» کافی نیست.")
            unit_price = to_rials(product.price)
            subtotal += unit_price * cart_line.quantity
            if subtotal > MAX_RIALS:
                raise CartRejected("مبلغ سبد از حد مجاز بیشتر است.")
            lines.append(
                QuoteLine(product, cart_line.quantity, unit_price * cart_line.quantity)
            )
            needs_shipping = needs_shipping or product.requires_shipping

        method = (
            await session.get(ShopShippingMethod, cart.shipping_method_id)
            if cart.shipping_method_id is not None else None
        )
        if method and method.store_id != cart.store_id:
            raise CartRejected("روش ارسال به این فروشگاه تعلق ندارد.")
        if needs_shipping and method is not None and not method.is_active:
            raise CartRejected("روش ارسال انتخاب‌شده غیرفعال شده است.")
        shipping = to_rials(method.price_irr) if needs_shipping and method else 0
        coupon = (
            await session.get(ShopCoupon, cart.coupon_id)
            if cart.coupon_id is not None else None
        )
        if coupon and coupon.store_id != cart.store_id:
            raise CartRejected("کد تخفیف به این فروشگاه تعلق ندارد.")
        discount = validate_coupon(coupon, subtotal) if coupon else 0
        total = subtotal + shipping - discount
        if not 0 < total <= MAX_RIALS:
            raise CartRejected("مبلغ سفارش معتبر نیست.")
        return CartQuote(
            tuple(lines), subtotal, discount, shipping, total,
            needs_shipping, method.name if method and needs_shipping else None,
            coupon.code if coupon else None,
        )

    async def _cart_reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Display all cart lines with real-time quantities and actions."""
        cart = await self._get_cart(event, session)
        if cart is None:
            return BotReply("سبد خرید خالی است.")
        try:
            quote = await self._quote(
                cart, session, bot_id=self._bot_id(event.platform),
            )
        except CartRejected as error:
            if str(error) == "سبد خرید خالی است.":
                return BotReply(
                    "سبد خرید خالی است.",
                    ((button("🛍 محصولات", "shop:categories"),),),
                )
            # Invalid stock or expired coupons must not trap the customer in
            # a view that cannot remove items or clear the selected coupon.
            result = await session.execute(
                select(ShopCartItem, Product)
                .join(Product, Product.id == ShopCartItem.product_id)
                .where(ShopCartItem.cart_id == cart.id)
                .order_by(ShopCartItem.id)
            )
            rows = [
                (button(
                    "🗑 حذف کالای غیرقابل خرید",
                    f"shop:remove:{item.product_id}",
                ),)
                for item, product in result.all()
            ]
            if cart.coupon_id is not None:
                rows.append((button("حذف کد تخفیف", "shop:clear_coupon"),))
            rows.append((button("🛍 محصولات", "shop:categories"),))
            return BotReply(
                f"⚠️ {error}\nبرای اصلاح سبد یکی از گزینه‌ها را انتخاب کنید.",
                tuple(rows),
            )
        rows = []
        details = ["🛒 سبد خرید"]
        for line in quote.lines:
            name = line.product.name[:70]
            details.append(
                f"• {name} × {line.quantity}: "
                f"{format_rials(line.line_total, self.display_unit)}"
            )
            product_id = line.product.id
            rows.append((
                button("➖", f"shop:dec:{product_id}"),
                button("➕", f"shop:inc:{product_id}"),
                button("🗑", f"shop:remove:{product_id}"),
            ))
        details.append(
            f"جمع کالاها: {format_rials(quote.subtotal, self.display_unit)}"
        )
        if quote.discount:
            details.append(
                f"تخفیف: {format_rials(quote.discount, self.display_unit)}"
            )
        if quote.shipping:
            details.append(
                f"ارسال: {format_rials(quote.shipping, self.display_unit)}"
            )
        details.append(
            f"مبلغ نهایی: {format_rials(quote.total, self.display_unit)}"
        )
        if quote.shipping_required:
            details.append(
                "نشانی ارسال: " +
                ("ثبت‌شده" if cart.shipping_address else "ثبت نشده")
            )
            details.append(
                "روش ارسال: " + (quote.shipping_label or "انتخاب نشده")
            )
            rows.append((
                button("📍 نشانی ارسال", "shop:address"),
                button("🚚 روش ارسال", "shop:shipping"),
            ))
        rows.append((button("🎟 کد تخفیف", "shop:coupon"),))
        if cart.coupon_id is not None:
            rows.append((button("حذف تخفیف", "shop:clear_coupon"),))
        rows.append((button("بررسی سفارش", "shop:checkout"),))
        rows.append((button("🛍 محصولات", "shop:categories"),))
        return BotReply("\n".join(details)[:4096], tuple(rows))

    async def _request_input(
        self, event: InboundEvent, session: AsyncSession, action: str,
    ) -> BotReply:
        """Stage address/coupon form state only for the requesting bot."""
        cart = await self._get_cart(event, session, create=True, lock=True)
        selected = "address" if action == "shop:address" else "coupon"
        if cart.is_shared:
            key = (self._bot_id(event.platform), event.user_id)
            row = await session.get(
                ShopCartInputSession, key, with_for_update=True,
            )
            if row is None:
                row = ShopCartInputSession(
                    bot_id=key[0], platform_user_id=key[1],
                    cart_id=cart.id,
                )
                session.add(row)
            row.cart_id = cart.id
            row.awaiting_input = selected
        else:
            cart.awaiting_input = selected
        await session.commit()
        return BotReply(
            "نشانی کامل ارسال را وارد کنید (۱۰ تا ۵۰۰ نویسه)."
            if selected == "address" else "کد تخفیف را ارسال کنید."
        )

    async def _accept_input(
        self, cart: ShopCart, value: str, session: AsyncSession,
        event: InboundEvent,
    ) -> BotReply:
        """Apply only the requesting bot's pending form to its verified cart."""
        row = None
        if cart.is_shared:
            row = await session.get(
                ShopCartInputSession,
                (self._bot_id(event.platform), event.user_id),
                with_for_update=True,
            )
            if row is None or row.cart_id != cart.id:
                raise CartRejected("فرم متعلق به این گفتگو نیست.")
        state = row.awaiting_input if row else cart.awaiting_input
        if state == "address":
            if not 10 <= len(value) <= 500:
                raise CartRejected("نشانی باید بین ۱۰ تا ۵۰۰ نویسه باشد.")
            cart.shipping_address = value
        elif state == "coupon":
            code = value.upper()
            if not re.fullmatch(r"[A-Z0-9_-]{3,32}", code):
                raise CartRejected("کد تخفیف معتبر نیست.")
            coupon = await session.scalar(select(ShopCoupon).where(
                ShopCoupon.store_id == cart.store_id,
                func.upper(ShopCoupon.code) == code,
            ))
            if coupon is None:
                raise CartRejected("کد تخفیف یافت نشد.")
            cart.coupon_id = coupon.id
        else:
            return BotReply("عملیات انتخاب‌شده معتبر نیست.")
        if row:
            row.awaiting_input = None
        else:
            cart.awaiting_input = None
        cart.revision += 1
        await session.commit()
        return BotReply(
            "✅ اطلاعات ثبت شد.",
            ((button("🛒 مشاهده سبد", "shop:cart"),),),
        )

    async def _shipping_choices(
        self, event: InboundEvent, session: AsyncSession,
        requested_page: int = 0
    ) -> BotReply:
        """Paginate arbitrary administrator-defined shipping methods."""
        store_id = (
            self.bot_context.store_id if self.bot_context
            else DEFAULT_STORE_ID
        )
        clause = (
            ShopShippingMethod.is_active.is_(True)
            & (ShopShippingMethod.store_id == store_id)
        )
        count = await session.scalar(
            select(func.count()).select_from(ShopShippingMethod).where(clause)
        )
        if not count:
            return BotReply("هیچ روش ارسالی تعریف نشده است.")
        last_page = (count - 1) // _SHIPPING_PAGE_SIZE
        page = min(requested_page, last_page)
        result = await session.execute(
            select(ShopShippingMethod)
            .where(clause)
            .order_by(ShopShippingMethod.position, ShopShippingMethod.id)
            .offset(page * _SHIPPING_PAGE_SIZE)
            .limit(_SHIPPING_PAGE_SIZE)
        )
        rows = [
            (button(
                f"{m.name[:35]} — {format_rials(m.price_irr, self.display_unit)}",
                f"shop:ship:{m.id}",
            ),)
            for m in result.scalars().all()
        ]
        controls = []
        if page:
            controls.append(button("قبلی", f"shop:shipping:{page - 1}"))
        if page < last_page:
            controls.append(button("بعدی", f"shop:shipping:{page + 1}"))
        if controls:
            rows.append(tuple(controls))
        rows.append((button("🛒 بازگشت به سبد", "shop:cart"),))
        return BotReply(
            f"🚚 انتخاب روش ارسال — صفحه {page + 1} از {last_page + 1}",
            tuple(rows),
        )

    async def _select_shipping(
        self, event: InboundEvent, session: AsyncSession, method_id: int
    ) -> BotReply:
        """Save the selected active shipping option."""
        shipping = await session.get(ShopShippingMethod, method_id)
        if (
            shipping is None or not shipping.is_active
            or shipping.store_id != (
                self.bot_context.store_id if self.bot_context
                else DEFAULT_STORE_ID
            )
        ):
            raise CartRejected("روش ارسال فعلی غیرفعال است.")
        cart = await self._get_cart(event, session, create=True, lock=True)
        cart.shipping_method_id = shipping.id
        cart.revision += 1
        await session.commit()
        return await self._cart_reply(event, session)

    async def _clear_coupon(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Remove a stale or unneeded promotional code."""
        cart = await self._get_cart(event, session, create=True, lock=True)
        cart.coupon_id = None
        cart.revision += 1
        await session.commit()
        return await self._cart_reply(event, session)

    async def _checkout_preview(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Show the final quote without starting any payment provider."""
        cart = await self._get_cart(event, session)
        if cart is None:
            raise CartRejected("سبد خرید خالی است.")
        if await self._existing_pending(session, cart, event) is not None:
            raise CartRejected("یک سفارش باز در انتظار بررسی دارید.")
        quote = await self._quote(
                cart, session, bot_id=self._bot_id(event.platform),
            )
        if quote.shipping_required and (
            not cart.shipping_address or not quote.shipping_label
        ):
            raise CartRejected("ابتدا نشانی و روش ارسال را در سبد ثبت کنید.")
        return BotReply(
            "تأیید سفارش بدون دریافت پول\n"
            f"تعداد اقلام: {sum(line.quantity for line in quote.lines)}\n"
            f"مبلغ نهایی: {format_rials(quote.total, self.display_unit)}\n"
            "ثبت نهایی فقط یک درخواست بررسی برای فروشنده ایجاد می‌کند.",
            ((
                button("✅ ثبت درخواست سفارش", f"shop:place:{cart.id}:{cart.revision}"),
                button("انصراف", "shop:cart"),
            ),),
        )

    async def _place_order(
        self, event: InboundEvent, session: AsyncSession,
        cart_id: int, expected_revision: int
    ) -> BotReply:
        """Atomically snapshot the basket and clear it, without taking money."""
        cart = await self._get_cart(event, session, lock=True)
        if cart is None or cart.id != cart_id:
            raise CartRejected("این سبد خرید به حساب شما تعلق ندارد.")
        checkout_key = (
            f"{self._bot_id(event.platform)}:{event.user_id}:{cart_id}:{expected_revision}"
        )
        existing = await session.scalar(
            select(ShopOrder).where(ShopOrder.checkout_key == checkout_key)
        )
        if existing is not None:
            return BotReply(
                f"درخواست سفارش #{existing.id} قبلاً ثبت شده است."
            )
        if cart.revision != expected_revision:
            raise CartRejected("محتوای سبد تغییر کرده؛ دوباره سفارش را بررسی کنید.")
        if await self._existing_pending(session, cart, event) is not None:
            raise CartRejected("یک سفارش باز در انتظار بررسی دارید.")
        await lock_bot_catalog_policy(
            session, self._bot_id(event.platform),
        )
        quote = await self._quote(
                cart, session, bot_id=self._bot_id(event.platform),
            )
        if quote.shipping_required and (
            not cart.shipping_address or not quote.shipping_label
        ):
            raise CartRejected("نشانی و روش ارسال را تکمیل کنید.")

        first = quote.lines[0]
        order = ShopOrder(
            store_id=cart.store_id,
            customer_id=cart.customer_id,
            bot_id=self._bot_id(event.platform),
            platform=event.platform.value,
            platform_user_id=event.user_id,
            chat_id=event.chat_id,
            product_id=first.product.id,
            product_name_snapshot=first.product.name,
            quantity=first.quantity,
            unit_price_irr=to_rials(first.product.price),
            total_irr=quote.total,
            provider="manual_review",
            status="pending_review",
            invoice_payload=secrets.token_urlsafe(32),
            checkout_key=checkout_key,
            subtotal_irr=quote.subtotal,
            discount_irr=quote.discount,
            shipping_irr=quote.shipping,
            shipping_address=cart.shipping_address if quote.shipping_required else None,
            shipping_method_snapshot=quote.shipping_label,
            coupon_code_snapshot=quote.coupon_code,
            coupon_id=cart.coupon_id,
        )
        session.add(order)
        await session.flush()
        # Snapshot the unit code on every immutable line. A later Product
        # unit edit must never change the meaning of a paid historical qty.
        selected_units = {line.product.uom_id for line in quote.lines}
        unit_codes = dict((await session.execute(select(
            ShopUom.id, ShopUom.code,
        ).where(
            ShopUom.id.in_(selected_units),
            ShopUom.store_id == cart.store_id,
        ))).all())
        if len(unit_codes) != len(selected_units):
            raise CartRejected("واحد اندازه‌گیری یکی از اقلام معتبر نیست.")
        for line in quote.lines:
            session.add(
                ShopOrderLine(
                    order_id=order.id,
                    product_id=line.product.id,
                    product_name_snapshot=line.product.name,
                    sku_snapshot=line.product.sku,
                    uom_code_snapshot=unit_codes[line.product.uom_id],
                    unit_price_irr=to_rials(line.product.price),
                    quantity=line.quantity,
                    total_irr=line.line_total,
                )
            )
        await session.execute(
            delete(ShopCartItem).where(ShopCartItem.cart_id == cart.id)
        )
        cart.shipping_address = None
        cart.shipping_method_id = None
        cart.coupon_id = None
        cart.awaiting_input = None
        if cart.is_shared:
            await session.execute(update(ShopCartInputSession).where(
                ShopCartInputSession.cart_id == cart.id,
            ).values(awaiting_input=None))
        cart.revision += 1
        await session.commit()
        return BotReply(
            f"✅ درخواست سفارش #{order.id} ثبت شد.\n"
            "هنوز پرداختی دریافت نشده است. فروشنده سفارش را بررسی می‌کند.",
            ((button("📦 سفارش‌های من", "shop:orders"),),),
        )
