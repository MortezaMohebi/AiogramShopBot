"""Authorize Store-owned admin refunds and select the original Stars Bot.

HTTP adapters retain staff RBAC and explicit operator confirmation. This
boundary checks the trusted current Store for every financial path, and
creates a Registry client only after its exact paid owner is verified.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models.shop_content import ShopOrder
from models.shop_multibot import (
    ShopBot,
    ShopBotCredential,
)
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from models.shop_store_commerce import ShopPaymentAccount
from services import shop_multibot_client
from services.shop_admin_security import SecurityRejected
from services.shop_bot_secrets import resolve_active_token
from services.shop_payments import PaymentRejected
from services.shop_refunds import ShopRefundService
from services.shop_store_context import StoreContext
from services.shop_wallet import ShopWalletService

def _require_client_identity(client, *, provider_id: int | None) -> None:
    """Reject unavailable or mismatched clients before claiming a refund."""
    if not callable(getattr(client, "refund_star_payment", None)) or (
        provider_id is not None and getattr(client, "id", None) != provider_id
    ):
        raise PaymentRejected(
            "ربات اصلی این پرداخت برای بازپرداخت در دسترس نیست."
        )


async def _stars_owner(
    session: AsyncSession,
    *,
    order: ShopOrder,
) -> ShopBot:
    """Validate the exact paid invoice, optional historical account and Bot."""
    attempt = await session.scalar(
        select(ShopPaymentAttempt)
        .where(
            ShopPaymentAttempt.order_id == order.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        order.platform != "telegram"
        or order.provider != "telegram_stars"
        or order.status not in {"paid", "paid_unfulfilled"}
        or order.paid_at is None
        or not order.telegram_payment_charge_id
        or order.payment_currency != "XTR"
        or type(order.payment_amount) is not int
        or order.payment_amount <= 0
        or attempt is None
        or attempt.status != "paid"
        or attempt.completed_at is None
        or attempt.store_id != order.store_id
        or attempt.bot_id != order.bot_id
        or attempt.platform != order.platform
        or attempt.provider != order.provider
        or attempt.currency != order.payment_currency
        or attempt.amount != order.payment_amount
        or attempt.payload != order.invoice_payload
    ):
        raise PaymentRejected("رسید پرداخت Stars با سفارش مطابقت ندارد.")
    if attempt.payment_account_id is not None:
        account = await session.get(
            ShopPaymentAccount,
            attempt.payment_account_id,
            populate_existing=True,
        )
        # A checkout account may be disabled after payment. Its immutable
        # owner/rail still identifies the historical refund obligation.
        if (
            account is None
            or account.store_id != order.store_id
            or account.platform != "telegram"
            or account.rail_type != "telegram_stars"
            or account.currency != "XTR"
        ):
            raise PaymentRejected(
                "اتصال پرداخت Stars به این فروشگاه تعلق ندارد."
            )
    bot = await session.get(ShopBot, order.bot_id, populate_existing=True)
    if (
        bot is None
        or bot.store_id != order.store_id
        or bot.platform != "telegram"
    ):
        raise PaymentRejected(
            "ربات اصلی پرداخت با فروشگاه سفارش مطابقت ندارد."
        )
    return bot


async def resolve_admin_refund(
    session: AsyncSession,
    *,
    scope: StoreContext,
    case_id: int,
    action: str,
    provider_reference: str = "",
) -> ShopRefundCase:
    """Resolve one explicitly approved refund within the trusted current Store.

    Registry Stars refunds use the Order's verified active credential and
    per-Bot provider factory. Disabled provider refunds create no client or
    pending claim.
    Manual evidence and internal credit use their existing audited services.
    """
    if not isinstance(scope, StoreContext):
        raise SecurityRejected("store_context_missing", 403)
    if (
        type(case_id) is not int
        or case_id <= 0
        or action
        not in {
            "manual",
            "store_credit",
            "stars",
        }
    ):
        raise PaymentRejected("پرونده یا روش بازپرداخت معتبر نیست.")
    # Match the core refund lock order, Case -> Order. The authorization check
    # is explicit even when an ORM identity was cached outside request scope.
    case = await session.scalar(
        select(ShopRefundCase)
        .where(
            ShopRefundCase.id == case_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise PaymentRejected("پرونده بازپرداخت یافت نشد.")
    order = await session.get(
        ShopOrder,
        case.order_id,
        with_for_update=True,
        populate_existing=True,
    )
    if order is None:
        raise PaymentRejected("سفارش پرونده بازپرداخت یافت نشد.")
    scope.require(order.store_id, write=True)
    reviewer = f"staff:{scope.staff_id}"
    if action == "manual":
        if order.provider not in {
            "bale_wallet",
            "telegram_fiat",
        } or not isinstance(
            provider_reference,
            str,
        ):
            raise PaymentRejected(
                "این پرداخت از مسیر تأیید دستی قابل بازپرداخت نیست."
            )
        return await ShopRefundService.confirm_manual(
            session,
            case_id=case_id,
            provider_reference=provider_reference.strip(),
            reviewer=reviewer,
        )
    if action == "store_credit":
        return await ShopWalletService.refund_order(
            session,
            case_id=case_id,
            actor=reviewer,
        )

    # Check the deployment gate before decryption, relay resolution or client
    # construction. Browser payloads cannot opt in to provider refunds.
    if getattr(config, "TELEGRAM_STARS_REFUNDS_ENABLED", False) is not True:
        raise PaymentRejected("بازپرداخت خودکار Stars غیرفعال است.")
    if case.status != "requested":
        raise PaymentRejected("این درخواست بازپرداخت آماده اقدام نیست.")
    bot = await _stars_owner(session, order=order)
    if (
        bot.runtime_owner != "registry"
        or bot.status != "active"
        or bot.verified_at is None
        or type(bot.provider_bot_id) is not int
        or bot.provider_bot_id <= 0
        or type(bot.credential_version) is not int
        or bot.credential_version <= 0
    ):
        raise PaymentRejected("ربات اصلی این پرداخت فعال و تأییدشده نیست.")
    credential = await session.scalar(
        select(ShopBotCredential)
        .where(
            ShopBotCredential.bot_id == bot.id,
            ShopBotCredential.version == bot.credential_version,
            ShopBotCredential.state == "active",
        )
        .execution_options(populate_existing=True)
    )
    if (
        credential is None
        or credential.source != "encrypted"
        or not credential.ciphertext
        or credential.verified_at is None
        or credential.verified_bot_id != bot.provider_bot_id
    ):
        raise PaymentRejected(
            "اعتبار تأییدشدهٔ ربات اصلی پرداخت در دسترس نیست."
        )
    attempted = False
    try:
        token = await session.run_sync(
            lambda sync: resolve_active_token(sync, bot_id=bot.id),
        )
        async with shop_multibot_client.provider_client(
            "telegram",
            token,
            bot_id=bot.id,
        ) as client:
            _require_client_identity(client, provider_id=bot.provider_bot_id)
            attempted = True
            return await ShopRefundService.refund_stars(
                session,
                case_id=case_id,
                bot=client,
                enabled=True,
                reviewer=reviewer,
            )
    except PaymentRejected:
        raise
    except Exception:
        # Connection/relay errors can include token-bearing URLs. Preserve
        # the core's durable pending receipt after any actual provider attempt.
        message = (
            "نتیجهٔ بازپرداخت نیازمند بررسی است؛ درخواست را تکرار نکنید."
            if attempted
            else "ربات اصلی این پرداخت برای بازپرداخت در دسترس نیست."
        )
        raise PaymentRejected(message) from None
