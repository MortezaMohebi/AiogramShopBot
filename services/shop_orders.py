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

    def __init__(self, display_unit: str = "IRR") -> None:
        """Select a display unit; money remains canonical integer IRR."""
        self.display_unit = display_unit

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
                rows.append((
                    InlineAction(
                        f"💳 پرداخت سفارش #{order.id}",
                        f"shop:pay:{order.id}",
                    ),
                ))
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
