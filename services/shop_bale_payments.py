"""Route authenticated Bale wallet events to the shared payment ledger.

The independent `inquireTransaction` check is mandatory for new orders.
Neither Bale nor Telegram shares raw numeric customer IDs with the other.
"""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.bale import BaleTransport
from channels.contracts import Platform
from models.shop_payment import ShopPaymentAttempt
from models.shop_scope import require_bot_id
from services.shop_payments import PaymentRejected, ShopPaymentService


async def _is_new_intent(
    session: AsyncSession, payload: Any,
    *, bot_id: str | None = None,
) -> bool:
    """Identify an invoice only within its authenticated bot scope."""
    if not isinstance(payload, str) or not payload:
        return False
    found = await session.scalar(
        select(ShopPaymentAttempt.id).where(
            ShopPaymentAttempt.payload == payload,
            ShopPaymentAttempt.bot_id == (
                require_bot_id(bot_id)
            ),
            ShopPaymentAttempt.platform == Platform.BALE.value,
        )
    )
    return found is not None


async def validate_bale_precheckout(
    session: AsyncSession,
    query: Mapping[str, Any],
    *, bot_id: str | None = None,
) -> tuple[bool, str | None]:
    """Check the correct order ledger before accepting Bale wallet payment."""
    if await _is_new_intent(
        session, query.get("invoice_payload"), bot_id=bot_id,
    ):
        payer = query.get("from")
        payer_id = payer.get("id") if isinstance(payer, Mapping) else None
        return await ShopPaymentService.precheckout(
            session,
            platform=Platform.BALE,
            payer_id=payer_id,
            payload=query.get("invoice_payload"),
            currency=query.get("currency"),
            amount=query.get("total_amount"),
            bot_id=bot_id,
        )
    return False, "فاکتور متعلق به این بات نیست."


async def settle_bale_payment(
    session: AsyncSession,
    transport: BaleTransport,
    *,
    payer_id: int,
    chat_id: int,
    payment: Mapping[str, Any],
    bot_id: str | None = None,
):
    """Verify native wallet evidence and commit the correct ledger once."""
    if not await _is_new_intent(
        session, payment.get("invoice_payload"), bot_id=bot_id,
    ):
        raise PaymentRejected("رسید متعلق به این بات نیست.")

    tx_id = payment.get("telegram_payment_charge_id")
    reference = payment.get("provider_payment_charge_id")
    amount = payment.get("total_amount")
    if (
        not isinstance(tx_id, str) or not tx_id
        or not isinstance(reference, str) or not reference
        or type(amount) is not int or amount <= 0
    ):
        raise PaymentRejected("شناسه یا مبلغ رسید کیف پول معتبر نیست.")
    evidence = await transport.inquire_transaction(tx_id)
    if not (
        evidence.get("status") == "paid"
        and str(evidence.get("id")) == tx_id
        and type(evidence.get("userID")) is int
        and evidence["userID"] == payer_id
        and type(evidence.get("amount")) is int
        and evidence["amount"] == amount
    ):
        raise PaymentRejected("استعلام مستقل کیف پول بله با رسید مطابقت ندارد.")

    return await ShopPaymentService.settle(
        session,
        platform=Platform.BALE,
        payer_id=payer_id,
        chat_id=chat_id,
        payload=payment.get("invoice_payload"),
        currency=payment.get("currency"),
        amount=amount,
        charge_id=tx_id,
        provider_charge_id=reference,
        bot_id=bot_id,
    )
