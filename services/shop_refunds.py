"""Audited refunds with Telegram Stars provider support and manual fallback.

The Bale Bot API snapshot has no authenticated refund method. Do not claim
a Bale or Telegram fiat refund until a human verifies provider evidence.
Stock is never silently returned upon refund of potentially delivered goods.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_content import ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_scope import legacy_id
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_payments import PaymentRejected

if TYPE_CHECKING:
    from aiogram import Bot


class ShopRefundService:
    """Control refund case creation and verified financial transitions."""

    @staticmethod
    async def request(
        session: AsyncSession,
        *,
        platform: Platform,
        payer_id: int,
        order_id: int,
        reason: str,
        bot_id: str | None = None,
    ) -> ShopRefundCase:
        """Open one provider-reconciliation case without issuing any refund."""
        if not 1 <= len(reason.strip()) <= 1000:
            raise PaymentRejected("دلیل درخواست بازپرداخت نامعتبر است.")
        order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.id == order_id,
                ShopOrder.bot_id == (bot_id or legacy_id(platform.value)),
                ShopOrder.platform == platform.value,
                ShopOrder.platform_user_id == payer_id,
            ).with_for_update()
        )
        if order is None or order.status not in ("paid", "paid_unfulfilled"):
            raise PaymentRejected(
                "تنها برای سفارش پرداخت‌شده می‌توان درخواست بازپرداخت داد."
            )
        existing = await session.scalar(
            select(ShopRefundCase).where(
                ShopRefundCase.order_id == order.id
            )
        )
        if existing is not None:
            return existing
        case = ShopRefundCase(
            order_id=order.id,
            actor=f"{bot_id or legacy_id(platform.value)}:{payer_id}",
            reason=reason.strip(),
            status="requested",
        )
        session.add(case)
        await session.commit()
        await session.refresh(case)
        return case

    @staticmethod
    async def _confirm(
        session: AsyncSession,
        *,
        case_id: int,
        provider_reference: str,
        reviewer: str,
    ) -> ShopRefundCase:
        """Record verified external refund, without unapproved restocking."""
        if (
            not 8 <= len(provider_reference) <= 128
            or not 1 <= len(reviewer) <= 120
        ):
            raise PaymentRejected("مدرک یا شناسه پیگیری بازپرداخت کافی نیست.")
        case = await session.scalar(
            select(ShopRefundCase).where(
                ShopRefundCase.id == case_id
            ).with_for_update()
        )
        if case is None:
            raise PaymentRejected("پرونده بازپرداخت یافت نشد.")
        if case.status == "confirmed":
            if case.provider_reference == provider_reference:
                return case
            raise PaymentRejected("این پرونده قبلاً با مدرک دیگری بسته شده است.")
        if case.status not in ("requested", "provider_pending"):
            raise PaymentRejected("این پرونده در وضعیت قابل تأیید نیست.")

        order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.id == case.order_id
            ).with_for_update()
        )
        attempt = await session.scalar(
            select(ShopPaymentAttempt).where(
                ShopPaymentAttempt.order_id == order.id
            ).with_for_update()
        )
        if (
            order.status not in ("paid", "paid_unfulfilled")
            or attempt is None
            or attempt.status != "paid"
        ):
            raise PaymentRejected("پرداخت اصلی معتبر نیست یا قبلاً بازگشت خورده است.")
        case.provider_reference = provider_reference
        case.resolution_note = f"Verified by {reviewer}"
        case.resolved_at = datetime.now(timezone.utc)
        case.status = "confirmed"
        attempt.status = "refunded"
        order.status = "refunded"
        await session.commit()
        return case

    @classmethod
    async def confirm_manual(
        cls,
        session: AsyncSession,
        *,
        case_id: int,
        provider_reference: str,
        reviewer: str,
    ) -> ShopRefundCase:
        """Record a manually verified fiat/Bale refund with a proof reference.

        This does NOT call or simulate any unsupported provider API. The
        reviewer is responsible for independently verifying actual settlement.
        Evidence of money already returned remains recordable during an
        uncertain digital delivery; recording it cannot cancel an accepted send.
        """
        case = await session.scalar(
            select(ShopRefundCase).where(ShopRefundCase.id == case_id)
        )
        if case is None:
            raise PaymentRejected("پرونده یافت نشد.")
        order = await session.get(ShopOrder, case.order_id)
        if order.provider == "telegram_stars":
            raise PaymentRejected(
                "بازپرداخت Stars فقط از مسیر رسمی Telegram Bot API مجاز است."
            )
        return await cls._confirm(
            session,
            case_id=case_id,
            provider_reference=provider_reference,
            reviewer=reviewer,
        )

    @classmethod
    async def refund_stars(
        cls,
        session: AsyncSession,
        *,
        case_id: int,
        bot: Bot,
        enabled: bool,
        reviewer: str,
    ) -> ShopRefundCase:
        """Issue exactly one operator-approved refundStarPayment request.

        Mark `provider_pending` before the network call. On timeout, do
        not resend automatically; a human must reconcile provider status.
        The shared Order lock excludes new digital claims until pending state
        is durable. An already in-flight or unknown send requires review first.
        """
        if not enabled:
            raise PaymentRejected("بازپرداخت خودکار Stars غیرفعال است.")
        case = await session.scalar(
            select(ShopRefundCase).where(
                ShopRefundCase.id == case_id
            ).with_for_update().execution_options(populate_existing=True)
        )
        if case is None or case.status != "requested":
            raise PaymentRejected("این درخواست بازپرداخت آماده اقدام نیست.")
        order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.id == case.order_id
            ).with_for_update().execution_options(populate_existing=True)
        )
        if (
            order is None or order.platform != Platform.TELEGRAM.value
            or order.provider != "telegram_stars"
            or order.status not in ("paid", "paid_unfulfilled")
            or not order.telegram_payment_charge_id
        ):
            raise PaymentRejected("این سفارش قابل بازپرداخت Stars نیست.")
        # A claim holds Delivery -> Order. Never lock Delivery here after
        # taking Order: reading its committed state avoids a deadlock while
        # the Order lock prevents queued work from becoming a new send.
        uncertain_delivery = await session.scalar(
            select(ShopDigitalDelivery.id).where(
                ShopDigitalDelivery.order_id == order.id,
                ShopDigitalDelivery.state.in_(("sending", "needs_review")),
            ).limit(1)
        )
        if uncertain_delivery is not None:
            raise PaymentRejected(
                "نتیجهٔ تحویل دیجیتال هنوز مشخص نیست؛ "
                "پیش از بازپرداخت، وضعیت تحویل را بررسی کنید."
            )
        case.status = "provider_pending"
        await session.commit()
        try:
            successful = await bot.refund_star_payment(
                user_id=order.platform_user_id,
                telegram_payment_charge_id=order.telegram_payment_charge_id,
            )
        except TelegramAPIError:
            raise PaymentRejected(
                "نتیجه بازپرداخت نامشخص است؛ بدون استعلام، درخواست را تکرار نکنید."
            ) from None
        if successful is not True:
            raise PaymentRejected(
                "Telegram بازپرداخت را تأیید نکرد؛ پرونده نیازمند بررسی است."
            )
        return await cls._confirm(
            session,
            case_id=case_id,
            provider_reference=order.telegram_payment_charge_id,
            reviewer=reviewer,
        )
