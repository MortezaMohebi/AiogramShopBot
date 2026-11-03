"""Send a frozen shared invoice through its own platform transport.

Only this boundary knows about Aiogram Bot, Bale HTTP, or merchant tokens.
The order and attempt are committed *before* any network request, so an
ambiguous timeout cannot trigger an untracked second invoice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import Platform
from services.shop_payment_rails import rail_enabled
from services.shop_payments import (
    InvoicePlan, PaymentRejected, ShopPaymentService,
)

if TYPE_CHECKING:
    from aiogram import Bot


async def send_order_invoice(
    session: AsyncSession,
    *,
    platform: Platform,
    user_id: int,
    order_id: int,
    telegram_bot: Bot | None = None,
    bale_transport: BaleTransport | None = None,
) -> InvoicePlan:
    """Issue only one allowed invoice; never silently retry an unknown send."""
    if platform == Platform.BALE:
        if bale_transport is None or not config.BALE_WALLET_PROVIDER_TOKEN:
            raise PaymentRejected("کیف پول بله برای این فروشگاه پیکربندی نشده است.")
    elif platform == Platform.TELEGRAM:
        if telegram_bot is None:
            raise PaymentRejected("اتصال پرداخت تلگرام در دسترس نیست.")
        if (
            config.TELEGRAM_FIAT_CHECKOUT_ENABLED
            and not config.TELEGRAM_FIAT_PROVIDER_TOKEN
        ):
            raise PaymentRejected("توکن درگاه ریالی تلگرام ثبت نشده است.")
    else:
        raise PaymentRejected("پیام‌رسان پشتیبانی نمی‌شود.")

    plan = await ShopPaymentService.begin(
        session,
        platform=platform,
        platform_user_id=user_id,
        order_id=order_id,
        bale_enabled=config.BALE_WALLET_CHECKOUT_ENABLED and await rail_enabled(session, "bale", "bale_wallet"),
        telegram_fiat_enabled=config.TELEGRAM_FIAT_CHECKOUT_ENABLED and await rail_enabled(session, "telegram", "telegram_fiat"),
        telegram_stars_enabled=config.TELEGRAM_STARS_CHECKOUT_ENABLED and await rail_enabled(session, "telegram", "telegram_stars"),
        telegram_minor_multiplier=config.TELEGRAM_IRR_MINOR_MULTIPLIER,
    )
    try:
        if platform == Platform.BALE:
            if plan.provider != "bale_wallet" or plan.currency != "IRR":
                raise PaymentRejected("صورتحساب کیف پول بله معتبر نیست.")
            await bale_transport.send_invoice(
                chat_id=plan.chat_id,
                title=plan.title,
                description=plan.description,
                payload=plan.payload,
                provider_token=config.BALE_WALLET_PROVIDER_TOKEN,
                amount_irr=plan.amount,
            )
        else:
            if plan.provider not in ("telegram_fiat", "telegram_stars"):
                raise PaymentRejected("درگاه پرداخت تلگرام برای این سفارش معتبر نیست.")
            args = {
                "chat_id": plan.chat_id,
                "title": plan.title,
                "description": plan.description,
                "payload": plan.payload,
                "currency": plan.currency,
                "prices": [
                    LabeledPrice(label=plan.title, amount=plan.amount)
                ],
                # Nonempty deep-link parameter prevents a forwarded invoice
                # from allowing a second user to pay someone else's order.
                "start_parameter": f"order_{plan.order_id}",
            }
            if plan.provider == "telegram_fiat":
                args["provider_token"] = config.TELEGRAM_FIAT_PROVIDER_TOKEN
            # XTR must not send a fiat provider token.
            await telegram_bot.send_invoice(**args)
    except (TelegramAPIError, BaleApiError, OSError, TimeoutError):
        await ShopPaymentService.mark_invoice_dispatch(
            session, plan.attempt_id, sent=False
        )
        raise PaymentRejected(
            "وضعیت ارسال فاکتور نامشخص است. "
            "برای جلوگیری از پرداخت تکراری، درخواست نیازمند بررسی مدیر است."
        ) from None

    await ShopPaymentService.mark_invoice_dispatch(
        session, plan.attempt_id, sent=True
    )
    return plan
