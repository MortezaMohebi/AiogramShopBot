"""Shared order history and safe cancellation for Telegram and Bale.

Purchase history does not depend on Bale's Wallet API or Telegram's Legacy
purchase records. Payment transactions are never cancelled by this service.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_checkout import ShopOrderLine
from models.shop_content import ShopOrder
from services.shop_money import format_rials
from services.shop_channel_features import get_features, inline_credit_label
from services.shop_payment_rails import rail_enabled
from services.shop_bot_catalog_acl import resolve_scope, visible_product_ids
from models.shop_scope import legacy_id
from services.shop_bot_context import BotContext
import config
from services.shop_refunds import ShopRefundService
from services.shop_payments import PaymentRejected

_CANCEL = re.compile(r"shop:cancelorder:([1-9][0-9]{0,18})\Z")
_REFUND = re.compile(r"shop:refundorder:([1-9][0-9]{0,18})\Z")

STATUS_NAMES = {
    "pending_review": "در انتظار بررسی فروشنده",
    "approved_unpaid": "بررسی شد؛ پرداخت نشده",
    "pending_payment": "در انتظار پرداخت",
    "paid": "پرداخت‌شده",
    "paid_unfulfilled": "پرداخت شده؛ نیازمند بررسی",
    "refunded": "بازپرداخت‌شده",
    "cancelled": "لغو‌شده",
}


class ShopOrdersFlow:
    """Provide one order-history experience for both messaging platforms."""

    def __init__(
        self, display_unit: str = "IRR",
        *, bot_context: BotContext | None = None,
    ) -> None:
        """Bind only a previously verified bot identity for every query."""
        self.display_unit = display_unit
        self.bot_context = bot_context

    def _bot_id(self, platform) -> str:
        """Scope all order reads and callbacks to the authenticated bot."""
        if self.bot_context is None:
            return legacy_id(platform.value)
        if self.bot_context.platform != platform:
            raise PaymentRejected("شناسه بات با پیام‌رسان تطبیق ندارد.")
        return self.bot_context.bot_id

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve order history or customer cancellation of an unpaid request."""
        action = event.callback_data or ""
        text = (event.text or "").strip()
        if action == "shop:orders" or text in (
            "/orders", "📦 سفارش‌های من",
        ):
            return await self._history(event, session)
        match = _REFUND.fullmatch(action)
        if match is not None:
            try:
                case = await ShopRefundService.request(
                    session,
                    platform=event.platform,
                    payer_id=event.user_id,
                    bot_id=self._bot_id(event.platform),
                    order_id=int(match.group(1)),
                    reason="Customer requested refund.",
                )
            except PaymentRejected as error:
                return BotReply(str(error))
            return BotReply(
                f"درخواست بازپرداخت سفارش ثبت شد. کد پیگیری #{case.id}. "
                "تا تأیید تراکنش مرجع، مبلغ بازگشته تلقی نمی‌شود."
            )
        match = _CANCEL.fullmatch(action)
        if match is not None:
            return await self._cancel(
                event, session, int(match.group(1))
            )
        return None

    async def _history(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Read only orders belonging to the current platform identity."""
        result = await session.execute(
            select(ShopOrder)
            .where(
                ShopOrder.bot_id == self._bot_id(event.platform),
                ShopOrder.platform == event.platform.value,
                ShopOrder.platform_user_id == event.user_id,
            )
            .order_by(ShopOrder.id.desc())
            .limit(10)
        )
        orders = result.scalars().all()
        if not orders:
            return BotReply(
                "هنوز سفارشی ثبت نکرده‌اید.",
                ((InlineAction("🛍 محصولات", "shop:categories"),),),
            )
        ids = [order.id for order in orders]
        counts_result = await session.execute(
            select(ShopOrderLine.order_id, func.sum(ShopOrderLine.quantity))
            .where(ShopOrderLine.order_id.in_(ids))
            .group_by(ShopOrderLine.order_id)
        )
        quantities = dict(counts_result.all())
        # A payment button must not be offered when the current bot ACL
        # denies an unpaid order. A customer's paid/refundable history remains
        # visible, and cancellation of the unpaid request stays available.
        order_items = await session.execute(
            select(ShopOrderLine.order_id, ShopOrderLine.product_id)
            .where(ShopOrderLine.order_id.in_(ids))
        )
        order_products: dict[int, set[int]] = {}
        all_products: set[int] = set()
        for order_id, product_id in order_items.all():
            order_products.setdefault(order_id, set()).add(product_id)
            all_products.add(product_id)
        allowed_products = await visible_product_ids(
            session,
            await resolve_scope(session, bot_id=self._bot_id(event.platform)),
            all_products,
        )
        features = await get_features(session, event.platform.value)
        credit_available = (
            features.store_credit_enabled and await rail_enabled(
                session, event.platform.value, "store_credit",
            )
        )
        external_ready = (
            config.BALE_WALLET_CHECKOUT_ENABLED
            and bool(config.BALE_WALLET_PROVIDER_TOKEN)
            and await rail_enabled(session, "bale", "bale_wallet")
        ) if event.platform.value == "bale" else (
            (config.TELEGRAM_STARS_CHECKOUT_ENABLED and
             await rail_enabled(session, "telegram", "telegram_stars"))
            or
            (config.TELEGRAM_FIAT_CHECKOUT_ENABLED
             and bool(config.TELEGRAM_FIAT_PROVIDER_TOKEN)
             and config.TELEGRAM_IRR_MINOR_MULTIPLIER > 0
             and await rail_enabled(session, "telegram", "telegram_fiat"))
        )
        lines = ["📦 سفارش‌های من"]
        rows: list[tuple[InlineAction, ...]] = []
        for order in orders:
            count = quantities.get(order.id, order.quantity)
            lines.append(
                f"#{order.id} — {count} کالا — "
                f"{format_rials(order.total_irr, self.display_unit)}\n"
                f"{STATUS_NAMES.get(order.status, 'در حال بررسی')}"
            )
            if order.status in ("paid", "paid_unfulfilled"):
                rows.append((
                    InlineAction(
                        f"درخواست بازپرداخت #{order.id}",
                        f"shop:refundorder:{order.id}",
                    ),
                ))
            if order.status == "approved_unpaid":
                # A denied order can still be cancelled or reconciled.
                # Only the creation of new invoice intents is prohibited.
                available_ids = order_products.get(order.id, set())
                if not available_ids or not available_ids <= allowed_products:
                    lines.append(
                        "دسترسی به یکی از کالاهای این سفارش تغییر کرده است؛ "
                        "پرداخت جدید برای آن مجاز نیست."
                    )
                else:
                    actions = []
                    if external_ready:
                        actions.append(InlineAction(
                            f"💳 پرداخت سفارش #{order.id}",
                            f"shop:pay:{order.id}",
                        ))
                    if credit_available:
                        actions.append(InlineAction(
                            inline_credit_label(features),
                            f"shop:creditpay:{order.id}",
                        ))
                    if actions:
                        rows.append(tuple(actions))
            if (
                order.provider == "manual_review"
                and order.status in ("pending_review", "approved_unpaid")
            ):
                rows.append((
                    InlineAction(
                        f"لغو درخواست #{order.id}",
                        f"shop:cancelorder:{order.id}",
                    ),
                ))
        rows.append((InlineAction("🛍 محصولات", "shop:categories"),))
        return BotReply("\n\n".join(lines), tuple(rows))

    async def _cancel(
        self, event: InboundEvent, session: AsyncSession, order_id: int
    ) -> BotReply:
        """Cancel only an unpaid review request owned by this exact identity."""
        result = await session.execute(
            select(ShopOrder).where(
                ShopOrder.id == order_id,
                ShopOrder.bot_id == self._bot_id(event.platform),
                ShopOrder.platform == event.platform.value,
                ShopOrder.platform_user_id == event.user_id,
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            return BotReply("سفارش یافت نشد.")
        if (
            order.provider != "manual_review"
            or order.status not in ("pending_review", "approved_unpaid")
        ):
            return BotReply(
                "این سفارش پرداخت‌شده، لغوشده یا در مرحله دیگری است؛ "
                "لغو خودکار آن امکان‌پذیر نیست."
            )
        order.status = "cancelled"
        await session.commit()
        return BotReply(
            f"درخواست سفارش #{order.id} لغو شد. مبلغی دریافت نشده است.",
            ((InlineAction("📦 سفارش‌های من", "shop:orders"),),),
        )
