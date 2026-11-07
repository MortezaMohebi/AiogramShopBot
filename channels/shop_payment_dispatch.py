"""Issue an immutable, store-scoped native invoice through the right bot.

New registry bots must own an explicit enabled PaymentAccount. Their Provider
Token is decrypted only on the backend; no shared platform-wide token fallback
is permitted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

import config
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import Platform
from models.shop_multibot import ShopBot
from models.shop_scope import require_bot_id
from services.shop_service_controls import service_enabled
from services.shop_payment_accounts import decrypt_provider_token
from services.shop_payment_rails import payment_account, rail_enabled
from services.shop_payments import InvoicePlan, PaymentRejected, ShopPaymentService

if TYPE_CHECKING:
    from aiogram import Bot


async def send_order_invoice(
    session: AsyncSession,
    *, platform: Platform, user_id: int, order_id: int,
    bot_id: str | None = None,
    telegram_bot: Bot | None = None,
    bale_transport: BaleTransport | None = None,
) -> InvoicePlan:
    """Send exactly one authorized invoice; never retry an uncertain result."""
    owner = require_bot_id(bot_id)
    bot = await session.get(ShopBot, owner)
    if bot is None or bot.platform != platform.value or bot.runtime_owner != "registry":
        raise PaymentRejected("هویت بات پرداخت معتبر نیست.")
    account_ids: dict[str, str] = {}
    bale_token = ""
    fiat_token = ""
    for rail_type in (
        ("bale_wallet",) if platform == Platform.BALE else
        ("telegram_fiat", "telegram_stars")
    ):
        account = await payment_account(session, bot_id=owner, rail_type=rail_type)
        if account is None:
            continue
        account_ids[rail_type] = account.id
        if rail_type == "bale_wallet":
            bale_token = decrypt_provider_token(account)
        elif rail_type == "telegram_fiat":
            fiat_token = decrypt_provider_token(account)

    if platform == Platform.BALE:
        if bale_transport is None or not bale_token:
            raise PaymentRejected("کیف پول بله برای این بات تعریف نشده است.")
    elif platform == Platform.TELEGRAM:
        if telegram_bot is None:
            raise PaymentRejected("اتصال پرداخت تلگرام در دسترس نیست.")
    else:
        raise PaymentRejected("پیام‌رسان پشتیبانی نمی‌شود.")

    bale_enabled = (
        service_enabled("bale-wallet")
        and bool(bale_token)
        and await rail_enabled(
            session, "bale", "bale_wallet", bot_id=owner,
        ) if platform == Platform.BALE else False
    )
    telegram_fiat_enabled = (
        service_enabled("telegram-fiat") and bool(fiat_token)
        and await rail_enabled(
            session, "telegram", "telegram_fiat", bot_id=owner,
        ) if platform == Platform.TELEGRAM else False
    )
    telegram_stars_enabled = (
        service_enabled("telegram-stars")
        and await rail_enabled(
            session, "telegram", "telegram_stars", bot_id=owner,
        ) if platform == Platform.TELEGRAM else False
    )
    plan = await ShopPaymentService.begin(
        session,
        platform=platform, platform_user_id=user_id, order_id=order_id,
        bot_id=owner,
        bale_enabled=bale_enabled,
        telegram_fiat_enabled=telegram_fiat_enabled,
        telegram_stars_enabled=telegram_stars_enabled,
        telegram_minor_multiplier=config.TELEGRAM_IRR_MINOR_MULTIPLIER,
        payment_account_ids=account_ids,
    )
    try:
        if platform == Platform.BALE:
            if plan.provider != "bale_wallet" or plan.currency != "IRR":
                raise PaymentRejected("صورتحساب کیف پول بله معتبر نیست.")
            await bale_transport.send_invoice(
                chat_id=plan.chat_id, title=plan.title,
                description=plan.description, payload=plan.payload,
                provider_token=bale_token, amount_irr=plan.amount,
            )
        else:
            if plan.provider not in ("telegram_fiat", "telegram_stars"):
                raise PaymentRejected("درگاه پرداخت برای این سفارش معتبر نیست.")
            args = {
                "chat_id": plan.chat_id, "title": plan.title,
                "description": plan.description,
                "payload": plan.payload, "currency": plan.currency,
                "prices": [LabeledPrice(label=plan.title, amount=plan.amount)],
                "start_parameter": f"order_{plan.order_id}",
            }
            if plan.provider == "telegram_fiat":
                args["provider_token"] = fiat_token
            # Telegram Stars uses XTR and no fiat Provider Token.
            await telegram_bot.send_invoice(**args)
    except (TelegramAPIError, BaleApiError, OSError, TimeoutError):
        # The upstream may have accepted the invoice already. Keep the
        # unresolved attempt visible for staff reconciliation, no auto-retry.
        await ShopPaymentService.mark_invoice_dispatch(
            session, plan.attempt_id, sent=False,
        )
        raise PaymentRejected(
            "وضعیت ارسال فاکتور نامشخص است و نیازمند بررسی مدیر است."
        ) from None

    await ShopPaymentService.mark_invoice_dispatch(
        session, plan.attempt_id, sent=True,
    )
    return plan
