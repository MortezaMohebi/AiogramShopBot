"""Provider-neutral invoice planning, pre-checkout and atomic paid settlement.

All incoming payment events are supplied by authenticated platform transports.
Neither invoice creation nor pre-checkout acknowledgement transfers inventory.
Only a matching successful-payment receipt is permitted to settle an order.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_cart import CartRejected, validate_coupon
from services.shop_bot_catalog_acl import (
    allowed_for_bot, lock_bot_catalog_policy,
)
from models.shop_scope import legacy_id
from services.shop_money import MAX_RIALS, to_rials


class PaymentRejected(ValueError):
    """A financial operation was refused without altering its settlement."""


@dataclass(frozen=True, slots=True)
class InvoicePlan:
    """Immutable parameters passed to one platform-specific sendInvoice."""

    attempt_id: int
    order_id: int
    chat_id: int
    provider: str
    payload: str
    currency: str
    amount: int
    title: str
    description: str


def frozen_stars_amount(pairs: list[tuple], *, expected_total: int | None) -> int:
    """Charge only the exact per-Order Stars price the customer accepted.

    A mutable Product.price_stars must never recalculate an approved
    amount. Invoice creation can follow seller approval much later.
    """
    if type(expected_total) is not int or expected_total <= 0:
        raise PaymentRejected("مبلغ Telegram Stars هنگام سفارش ثبت نشده است.")
    value = 0
    for line, product in pairs:
        price = line.unit_price_stars_snapshot
        if (
            product.product_type != "digital"
            or type(line.quantity) is not int or line.quantity <= 0
            or type(price) is not int or price <= 0
        ):
            raise PaymentRejected("قیمت ذخیره‌شدهٔ Telegram Stars معتبر نیست.")
        value += price * line.quantity
    if value != expected_total or value > 999_999_999_999:
        raise PaymentRejected(
            "مبلغ فاکتور با مبلغ تأییدشدهٔ Telegram Stars مطابقت ندارد."
        )
    return value


class ShopPaymentService:
    """Coordinate Telegram and Bale payments over one shared order ledger."""

    @staticmethod
    async def begin(
        session: AsyncSession,
        *,
        platform: Platform,
        platform_user_id: int,
        order_id: int,
        bale_enabled: bool,
        bot_id: str | None = None,
        telegram_fiat_enabled: bool,
        telegram_stars_enabled: bool,
        telegram_minor_multiplier: int,
        payment_account_ids: dict[str, str] | None = None,
    ) -> InvoicePlan:
        """Create one invoice intent under a locked approved, unpaid order.

        The caller must commit the intent before calling the remote API.
        A repeated button press cannot issue a second invoice for this order.
        """
        if type(order_id) is not int or order_id <= 0:
            raise PaymentRejected("شناسه سفارش معتبر نیست.")
        if type(platform_user_id) is not int or platform_user_id <= 0:
            raise PaymentRejected("خریدار معتبر نیست.")
        owner = bot_id or legacy_id(platform.value)
        result = await session.execute(
            select(ShopOrder).where(
                ShopOrder.id == order_id,
                ShopOrder.bot_id == owner,
                ShopOrder.platform == platform.value,
                ShopOrder.platform_user_id == platform_user_id,
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise PaymentRejected("سفارش متعلق به این حساب نیست.")
        from models.shop_multibot import ShopBot
        bot = await session.get(ShopBot, owner)
        if bot is None or bot.platform != platform.value or bot.store_id != order.store_id:
            raise PaymentRejected("مالکیت فروشگاه سفارش معتبر نیست.")
        if order.terms_accepted_at is None:
            raise PaymentRejected("شرایط فروش این سفارش تأیید نشده است.")
        if order.provider != "manual_review" or order.status != "approved_unpaid":
            raise PaymentRejected(
                "این سفارش آماده صدور فاکتور جدید نیست؛ "
                "وضعیت پرداخت را در سفارش‌های من بررسی کنید."
            )
        if await session.scalar(
            select(ShopPaymentAttempt.id).where(
                ShopPaymentAttempt.order_id == order.id
            )
        ):
            raise PaymentRejected("برای این سفارش قبلاً فاکتور ساخته شده است.")

        rows = await session.execute(
            select(ShopOrderLine, Product)
            .join(Product, ShopOrderLine.product_id == Product.id)
            .where(ShopOrderLine.order_id == order.id)
            .order_by(ShopOrderLine.product_id)
        )
        pairs = rows.all()
        if not pairs:
            raise PaymentRejected("اقلام این سفارش وجود ندارند.")
        # Only creation of a NEW payment intent is gated; already-paid
        # receipts remain reconcilable by settle() after policy changes.
        await lock_bot_catalog_policy(session, owner)
        if not await allowed_for_bot(
            session, owner,
            [product.id for _, product in pairs],
        ):
            raise PaymentRejected(
                "یک یا چند کالای سفارش در این بات دیگر قابل خرید نیستند."
            )
        subtotal = sum(line.total_irr for line, _ in pairs)
        if (
            type(order.total_irr) is not int or order.total_irr <= 0
            or subtotal != order.subtotal_irr
            or order.total_irr != (
                subtotal - (order.discount_irr or 0)
                + (order.shipping_irr or 0)
            )
            or order.total_irr > MAX_RIALS
        ):
            raise PaymentRejected("مبلغ سفارش با صورت‌حساب سازگار نیست.")

        types = {product.product_type for _, product in pairs}
        if not types <= {"physical", "digital"}:
            raise PaymentRejected("نوع کالا معتبر نیست.")
        for line, product in pairs:
            if (
                line.quantity < 1 or line.unit_price_irr < 0
                or line.total_irr != line.quantity * line.unit_price_irr
                or product.stock_quantity < line.quantity
                or not product.is_published
            ):
                raise PaymentRejected("قیمت یا موجودی اقلام سفارش نیازمند بررسی است.")
        if any(product.requires_shipping for _, product in pairs):
            if not order.shipping_address or not order.shipping_method_snapshot:
                raise PaymentRejected("نشانی یا روش ارسال سفارش ناقص است.")

        if order.coupon_id is not None:
            coupon = await session.get(ShopCoupon, order.coupon_id)
            if coupon is None:
                raise PaymentRejected("کد تخفیف سفارش حذف شده است.")
            try:
                discount = validate_coupon(coupon, subtotal)
            except CartRejected:
                raise PaymentRejected("کد تخفیف دیگر معتبر نیست.") from None
            if (
                discount != order.discount_irr
                or coupon.code != order.coupon_code_snapshot
            ):
                raise PaymentRejected("تخفیف سفارش باید دوباره محاسبه شود.")

        if platform == Platform.BALE:
            if not bale_enabled:
                raise PaymentRejected("پرداخت کیف پول بله غیرفعال است.")
            provider, currency, amount = (
                "bale_wallet", "IRR", to_rials(order.total_irr)
            )
        elif types == {"digital"}:
            if not telegram_stars_enabled:
                raise PaymentRejected("پرداخت Telegram Stars فعال نشده است.")
            if (
                order.coupon_id is not None or order.discount_irr
                or order.shipping_irr
                or any(p.requires_shipping for _, p in pairs)
            ):
                raise PaymentRejected(
                    "تخفیف ریالی و ارسال با فاکتور Stars سازگار نیستند."
                )
            amount = frozen_stars_amount(
                pairs, expected_total=order.total_stars_snapshot,
            )
            provider, currency = "telegram_stars", "XTR"
        elif types == {"physical"}:
            if not telegram_fiat_enabled or telegram_minor_multiplier == 0:
                raise PaymentRejected(
                    "درگاه پرداخت ریالی تلگرام یا ضریب واحد آن تأیید نشده است."
                )
            if telegram_minor_multiplier not in (1, 10, 100):
                raise PaymentRejected("ضریب واحد پول تلگرام نادرست است.")
            amount = order.total_irr * telegram_minor_multiplier
            provider, currency = "telegram_fiat", "IRR"
        else:
            raise PaymentRejected(
                "کالاهای دیجیتال و فیزیکی در تلگرام باید جدا پرداخت شوند."
            )

        # Telegram requires a positive integer at most 12 decimal digits.
        if type(amount) is not int or not 1 <= amount <= 999_999_999_999:
            raise PaymentRejected("مبلغ فاکتور از محدوده مجاز خارج است.")

        # The original checkout payload is random and uniquely indexed.
        intent = ShopPaymentAttempt(
            store_id=order.store_id,
            payment_account_id=(
                (payment_account_ids or {}).get(provider)
            ),
            order_id=order.id,
            bot_id=owner,
            platform=platform.value,
            provider=provider,
            currency=currency,
            amount=amount,
            payload=order.invoice_payload,
            status="dispatching",
        )
        order.provider = provider
        order.status = "pending_payment"
        order.payment_currency = currency
        order.payment_amount = amount
        session.add(intent)
        await session.commit()
        await session.refresh(intent)
        return InvoicePlan(
            attempt_id=intent.id,
            order_id=order.id,
            chat_id=order.chat_id,
            provider=provider,
            payload=intent.payload,
            currency=currency,
            amount=amount,
            title=f"سفارش #{order.id}"[:32],
            description=f"پرداخت {len(pairs)} قلم سفارش شماره {order.id}"[:255],
        )

    @staticmethod
    async def mark_invoice_dispatch(
        session: AsyncSession, attempt_id: int, *, sent: bool
    ) -> None:
        """Record a send result; unknown delivery must never be auto-retried."""
        intent = await session.scalar(
            select(ShopPaymentAttempt).where(
                ShopPaymentAttempt.id == attempt_id
            ).with_for_update()
        )
        if intent is not None and intent.status == "dispatching":
            intent.status = "invoice_sent" if sent else "dispatch_unknown"
            await session.commit()

    @staticmethod
    async def precheckout(
        session: AsyncSession,
        *,
        platform: Platform,
        payer_id: int,
        payload: str,
        currency: str,
        amount: int,
        bot_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Validate immutable payment data before acknowledging the provider."""
        if (
            type(payer_id) is not int or payer_id <= 0
            or not isinstance(payload, str)
            or type(amount) is not int or amount <= 0
        ):
            return False, "مشخصات پرداخت نامعتبر است."
        row = await session.execute(
            select(ShopPaymentAttempt, ShopOrder)
            .join(ShopOrder, ShopOrder.id == ShopPaymentAttempt.order_id)
            .where(
                ShopPaymentAttempt.payload == payload,
                ShopPaymentAttempt.bot_id == (bot_id or legacy_id(platform.value)),
                ShopOrder.bot_id == (bot_id or legacy_id(platform.value)),
                ShopPaymentAttempt.platform == platform.value,
            )
        )
        pair = row.one_or_none()
        if pair is None:
            return False, "فاکتور پیدا نشد."
        intent, order = pair
        if (
            intent.status not in (
                "dispatching", "invoice_sent", "dispatch_unknown"
            )
            or order.status != "pending_payment"
            or order.platform_user_id != payer_id
            or intent.currency != currency
            or intent.amount != amount
            or order.payment_currency != currency
            or order.payment_amount != amount
        ):
            return False, "مبلغ یا مالک فاکتور مطابقت ندارد."
        lines_result = await session.execute(
            select(ShopOrderLine, Product)
            .join(Product, Product.id == ShopOrderLine.product_id)
            .where(ShopOrderLine.order_id == order.id)
        )
        pairs = lines_result.all()
        if not pairs or not await allowed_for_bot(
            session, bot_id or legacy_id(platform.value),
            [product.id for _, product in pairs],
        ):
            return False, "یک یا چند کالای سفارش در این بات غیرمجاز شده‌اند."
        if any(
            product.stock_quantity < line.quantity
            or not product.is_published
            for line, product in pairs
        ):
            return False, "موجودی سفارش کافی نیست."
        if order.coupon_id is not None:
            coupon = await session.get(ShopCoupon, order.coupon_id)
            if coupon is None:
                return False, "کد تخفیف دیگر معتبر نیست."
            try:
                if validate_coupon(coupon, order.subtotal_irr) != order.discount_irr:
                    return False, "مبلغ تخفیف تغییر کرده است."
            except CartRejected:
                return False, "کد تخفیف منقضی شده است."
        return True, None

    @staticmethod
    async def settle(
        session: AsyncSession,
        *,
        platform: Platform,
        payer_id: int,
        chat_id: int,
        payload: str,
        currency: str,
        amount: int,
        charge_id: str,
        provider_charge_id: str | None,
        bot_id: str | None = None,
    ) -> tuple[ShopOrder, bool]:
        """Persist one verified receipt and allocate *all* available stock.

        Call only after the actual Telegram successful_payment update or Bale's
        successful_payment plus independent paid inquireTransaction evidence.
        If any line/coupon is unavailable, record paid_unfulfilled instead of
        partially deducting stock or silently losing received money.
        """
        if (
            type(payer_id) is not int or payer_id <= 0
            or type(chat_id) is not int or chat_id <= 0
            or not isinstance(payload, str)
            or not 1 <= len(payload.encode("utf-8")) <= 128
            or type(amount) is not int or amount <= 0
            or not isinstance(charge_id, str)
            or not 1 <= len(charge_id) <= 128
            or provider_charge_id is not None
            and (
                not isinstance(provider_charge_id, str)
                or not 1 <= len(provider_charge_id) <= 128
            )
        ):
            raise PaymentRejected("رسید پرداخت معتبر نیست.")

        result = await session.execute(
            select(ShopPaymentAttempt, ShopOrder)
            .join(ShopOrder, ShopOrder.id == ShopPaymentAttempt.order_id)
            .where(
                ShopPaymentAttempt.payload == payload,
                ShopPaymentAttempt.bot_id == (bot_id or legacy_id(platform.value)),
                ShopOrder.bot_id == (bot_id or legacy_id(platform.value)),
                ShopPaymentAttempt.platform == platform.value,
            )
            .with_for_update(of=(ShopPaymentAttempt, ShopOrder))
        )
        row = result.one_or_none()
        if row is None:
            raise PaymentRejected("رسید به سفارش شناخته‌شده‌ای تعلق ندارد.")
        intent, order = row
        if (
            order.platform_user_id != payer_id
            or order.chat_id != chat_id
            or order.payment_currency != currency
            or order.payment_amount != amount
            or intent.currency != currency
            or intent.amount != amount
            or order.provider != intent.provider
        ):
            raise PaymentRejected("اطلاعات رسید با فاکتور مطابقت ندارد.")

        if intent.status in ("paid", "refunded"):
            if (
                order.telegram_payment_charge_id == charge_id
                and order.provider_payment_charge_id == provider_charge_id
            ):
                return order, False
            raise PaymentRejected("این سفارش با رسید متفاوتی ثبت شده است.")
        if order.status != "pending_payment" or intent.status not in (
            "dispatching", "invoice_sent", "dispatch_unknown"
        ):
            raise PaymentRejected("وضعیت سفارش امکان تسویه ندارد.")

        rows = await session.execute(
            select(ShopOrderLine, Product)
            .join(Product, Product.id == ShopOrderLine.product_id)
            .where(ShopOrderLine.order_id == order.id)
            .order_by(ShopOrderLine.product_id)
            .with_for_update(of=Product)
        )
        pairs = rows.all()
        allocated = bool(pairs) and all(
            line.quantity > 0 and product.stock_quantity >= line.quantity
            and product.is_published
            for line, product in pairs
        )
        coupon = None
        if order.coupon_id is not None:
            coupon = await session.scalar(
                select(ShopCoupon).where(
                    ShopCoupon.id == order.coupon_id
                ).with_for_update()
            )
            if coupon is None:
                allocated = False
            else:
                try:
                    allocated = allocated and (
                        validate_coupon(coupon, order.subtotal_irr)
                        == order.discount_irr
                    )
                except CartRejected:
                    allocated = False

        if allocated:
            for line, product in pairs:
                product.stock_quantity -= line.quantity
            if coupon is not None:
                coupon.used_count += 1
            order.status = "paid"
        else:
            order.status = "paid_unfulfilled"
            # Track the refund/reconciliation obligation rather than pretending
            # an inventory-unavailable order never received a payment.
            existing = await session.scalar(
                select(ShopRefundCase.id).where(
                    ShopRefundCase.order_id == order.id
                )
            )
            if existing is None:
                session.add(
                    ShopRefundCase(
                        order_id=order.id,
                        reason="Payment received; inventory or coupon unavailable.",
                        actor="system",
                        status="requested",
                    )
                )

        order.telegram_payment_charge_id = charge_id
        order.provider_payment_charge_id = provider_charge_id
        order.paid_at = datetime.now(timezone.utc)
        intent.status = "paid"
        intent.completed_at = order.paid_at
        # The payment ledger is authoritative. An operational notice is a
        # best-effort Outbox append in a SAVEPOINT inside the same transaction;
        # a notification failure must never undo a valid provider receipt.
        try:
            async with session.begin_nested():
                from models.shop_multibot import ShopBot
                from services.shop_bot_context import BotContext
                from services.shop_customer_notifications import (
                    enqueue_notification,
                )

                bot = await session.get(ShopBot, order.bot_id)
                if bot is not None and bot.store_id == order.store_id:
                    context = BotContext(
                        bot_id=bot.id, store_id=bot.store_id,
                        platform=platform, provider_bot_id=bot.provider_bot_id,
                        status=bot.status, runtime_owner=bot.runtime_owner,
                        credential_version=bot.credential_version,
                        registry_version=bot.version,
                    )
                    notice = (
                        f"✅ پرداخت سفارش #{order.id} تأیید شد."
                        if order.status == "paid"
                        else f"✅ پرداخت سفارش #{order.id} دریافت شد؛ "
                             "برای تحویل نیازمند بررسی فروشنده است."
                    )
                    await enqueue_notification(
                        session, context=context,
                        user_id=payer_id, topic="order",
                        event_key=f"order_paid:{order.id}:{intent.id}",
                        body=notice,
                    )
        except Exception:
            # Expose metadata only; no user message, Token or payment receipt.
            import logging
            logging.getLogger(__name__).exception(
                "Order notice Outbox staging failed for order %s; "
                "provider settlement is still authoritative.",
                order.id,
            )
        await session.commit()
        return order, True
