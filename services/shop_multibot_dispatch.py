"""Shared Telegram/Bale multi-bot commerce dispatcher with verified BotContext.

The HTTP route and polling supervisor authenticate the Bot API credential
before constructing this context. No callback or message body may select an
arbitrary bot ID. Every operation resolves customer/credit/order scope from
that server-provided identity, and settlement runs before maintenance gates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from channels.contracts import BotReply, InboundEvent, Platform, normalize_update
from channels.shop_payment_dispatch import send_order_invoice
from channels.telegram import TelegramTransport
from db import session_maker
from services.shop_bale_payments import (
    settle_bale_payment, validate_bale_precheckout,
)
from services.shop_bot_context import BotContext
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_identity import is_blocked, register_customer
from services.shop_orders import ShopOrdersFlow
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_referrals import ShopReferralService

LOG = logging.getLogger(__name__)


async def _send(context: BotContext, client, chat_id: int, reply: BotReply) -> None:
    """Send one finalized message through only the current bot's transport."""
    if context.platform == Platform.TELEGRAM:
        await TelegramTransport(
            client, bot_id=context.bot_id,
        ).send(chat_id, reply)
    else:
        await client.send(chat_id, reply)


async def _acknowledge(context: BotContext, client, query_id: str) -> None:
    """Acknowledge callback presses even when a bot is paused or disabled."""
    if context.platform == Platform.TELEGRAM:
        await client.answer_callback_query(
            callback_query_id=query_id, cache_time=0,
        )
    else:
        await client.acknowledge(query_id)


async def _pre_checkout(context: BotContext, client, payload: Mapping) -> dict:
    """Check native invoice ownership before the provider charges the payer."""
    query = payload.get("pre_checkout_query")
    if not isinstance(query, dict):
        return {"status": "ignored"}
    query_id = query.get("id")
    payer = query.get("from")
    if (
        not isinstance(query_id, str) or not query_id
        or not isinstance(payer, dict)
        or type(payer.get("id")) is not int
    ):
        raise ValueError("Invalid pre-checkout provider payload")
    async with session_maker() as db:
        if context.platform == Platform.BALE:
            accepted, reason = await validate_bale_precheckout(
                db, query, bot_id=context.bot_id,
            )
        else:
            accepted, reason = await ShopPaymentService.precheckout(
                db, platform=context.platform,
                payer_id=payer["id"],
                payload=query.get("invoice_payload"),
                currency=query.get("currency"),
                amount=query.get("total_amount"),
                bot_id=context.bot_id,
            )
    if context.platform == Platform.TELEGRAM:
        await client.answer_pre_checkout_query(
            pre_checkout_query_id=query_id,
            ok=accepted,
            error_message=reason if not accepted else None,
        )
    else:
        await client.answer_pre_checkout(
            query_id, accepted=accepted, error_message=reason,
        )
    return {"status": "accepted" if accepted else "declined"}


async def _settle(context: BotContext, client, payload: Mapping) -> dict:
    """Reconcile a paid receipt even while the store is paused or disabled."""
    message = payload.get("message")
    if not isinstance(message, dict):
        return {"status": "ignored"}
    payment = message.get("successful_payment")
    if not isinstance(payment, dict):
        return {"status": "ignored"}
    payer, chat = message.get("from"), message.get("chat")
    if (
        not isinstance(payer, dict)
        or type(payer.get("id")) is not int
        or not isinstance(chat, dict)
        or chat.get("type") != "private"
        or type(chat.get("id")) is not int
        or payer["id"] != chat["id"]
    ):
        raise ValueError("Invalid successful-payment owner")
    async with session_maker() as db:
        if context.platform == Platform.BALE:
            order, changed = await settle_bale_payment(
                db, client, payer_id=payer["id"],
                chat_id=chat["id"], payment=payment,
                bot_id=context.bot_id,
            )
        else:
            order, changed = await ShopPaymentService.settle(
                db,
                platform=context.platform, payer_id=payer["id"],
                chat_id=chat["id"],
                payload=payment.get("invoice_payload"),
                currency=payment.get("currency"),
                amount=payment.get("total_amount"),
                charge_id=payment.get("telegram_payment_charge_id"),
                provider_charge_id=payment.get("provider_payment_charge_id"),
                bot_id=context.bot_id,
            )

    # This is an already committed financial transaction. Notification or
    # referral failure cannot trigger a second settlement or stock decrement.
    if changed:
        await _send(
            context, client, chat["id"],
            BotReply(
                f"✅ پرداخت سفارش #{order.id} تأیید شد."
                if order.status == "paid"
                else f"⚠️ رسید #{order.id} ثبت شد؛ بررسی فروشنده لازم است."
            ),
        )
        if order.status == "paid":
            try:
                async with session_maker() as reward_db:
                    await ShopReferralService.award_for_paid_order(
                        reward_db, order.id,
                    )
            except Exception:
                LOG.warning(
                    "Post-settlement referral needs review; order_id=%s",
                    order.id,
                )
    return {"status": "settled" if changed else "already_settled"}


async def dispatch(
    context: BotContext, client, payload: Mapping,
) -> dict:
    """Process one uniquely claimed provider update and return a safe status."""
    if not isinstance(payload, Mapping):
        raise ValueError("Provider payload must be an object")
    if isinstance(payload.get("pre_checkout_query"), dict):
        return await _pre_checkout(context, client, payload)
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(
        message.get("successful_payment"), dict,
    ):
        return await _settle(context, client, payload)

    event = normalize_update(context.platform, payload)
    if event is None:
        return {"status": "ignored"}
    if event.callback_query_id:
        await _acknowledge(context, client, event.callback_query_id)

    # A customer may request a refund on a paid order while shopping is off.
    refund_request = (
        bool(event.callback_data)
        and event.callback_data.startswith("shop:refundorder:")
    )
    async with session_maker() as db:
        if not refund_request and context.status != "active":
            if context.status == "disabled":
                return {"status": "disabled"}
            from models.shop_bot_operations import ShopBotOperations

            options = await db.get(ShopBotOperations, context.bot_id)
            note = (
                options.maintenance_message
                if options and options.maintenance_message
                else "فروشگاه موقتاً در حال نگهداری است."
            )
            await _send(context, client, event.chat_id, BotReply(note))
            return {"status": "maintenance"}

        if not refund_request:
            await register_customer(
                db, bot_id=context.bot_id, platform=context.platform,
                platform_user_id=event.user_id,
                username=_user_name(payload),
                first_name=_first_name(payload),
            )
        if await is_blocked(
            db, bot_id=context.bot_id, platform=context.platform,
            platform_user_id=event.user_id,
        ) and not refund_request:
            return {"status": "blocked"}

        if event.callback_data and event.callback_data.startswith(
            "shop:pay:"
        ):
            try:
                order_id = int(event.callback_data.removeprefix("shop:pay:"))
                await send_order_invoice(
                    db,
                    platform=context.platform, user_id=event.user_id,
                    bot_id=context.bot_id, order_id=order_id,
                    telegram_bot=client if context.platform == Platform.TELEGRAM
                    else None,
                    bale_transport=client if context.platform == Platform.BALE
                    else None,
                )
            except (PaymentRejected, ValueError) as error:
                await _send(
                    context, client, event.chat_id, BotReply(str(error)),
                )
            return {"status": "invoice_requested"}

        flows = (
            ShopOrdersFlow(bot_context=context),
        ) if refund_request else (
            ShopEngagementFlow(bot_context=context),
            ShopOrdersFlow(bot_context=context),
            ShopCartFlow(bot_context=context),
            CatalogFlow(bot_context=context),
        )
        reply = None
        for flow in flows:
            reply = await flow.reply(event, db)
            if reply is not None:
                break
    if reply is None:
        return {"status": "ignored"}
    await _send(context, client, event.chat_id, reply)
    return {"status": "processed"}


def _sender(payload: Mapping) -> Mapping:
    """Read provider-authoritative message/callback sender metadata."""
    source = payload.get("callback_query") or payload.get("message") or {}
    sender = source.get("from") if isinstance(source, Mapping) else {}
    return sender if isinstance(sender, Mapping) else {}


def _user_name(payload: Mapping) -> str | None:
    """Return a bounded, non-secret public handle from the authenticated user."""
    name = _sender(payload).get("username")
    return name[:255] if isinstance(name, str) else None


def _first_name(payload: Mapping) -> str | None:
    """Return a bounded display name without trusting a bot identifier."""
    name = _sender(payload).get("first_name")
    return name[:255] if isinstance(name, str) else None
