"""Shared Telegram/Bale multi-bot commerce dispatcher with verified BotContext.

The HTTP route and polling supervisor authenticate the Bot API credential
before constructing this context. No callback or message body may select an
arbitrary bot ID. Every operation resolves customer/credit/order scope from
that server-provided identity, and settlement runs before maintenance gates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from channels.contracts import BotReply, InboundEvent, Platform, normalize_update
from channels.shop_payment_dispatch import send_order_invoice
from channels.telegram import TelegramTransport
from db import session_maker
from services.shop_bale_payments import (
    settle_bale_payment,
    validate_bale_precheckout,
)
from services.shop_bot_context import BotContext
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow
from services.shop_customer_experience import (
    CustomerExperienceFlow,
    clear_pending_on_navigation,
    should_clear_chat_state,
)
from services.shop_customer_notification_dispatch import deliver_order_paid_once
from services.shop_customer_support import CustomerSupportFlow, is_support_action
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_identity import is_blocked, register_customer
from services.shop_orders import ShopOrdersFlow
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_referrals import ShopReferralService
from services.shop_runtime.ingress import try_ingress

LOG = logging.getLogger(__name__)
_REFUND_ACTION = re.compile(r"shop:refundorder:([1-9][0-9]{0,18})\Z")
_ORDER_READ_ACTION = re.compile(r"ux:order:(detail|track):([1-9][0-9]{0,18})\Z")


async def _paused_service_route(db, context: BotContext, event: InboundEvent) -> str | None:
    """Allow only bounded after-sale help while cart and payment entry stay gated."""
    action = event.callback_data or ""
    text = (event.text or "").strip()
    if is_support_action(action) or text in {
        "/support", "/paysupport", "/ticket", "🆘 پشتیبانی", "💬 پشتیبانی",
    }:
        return "support"
    if action == "shop:orders" or _REFUND_ACTION.fullmatch(action) or text in {
        "/orders", "📦 سفارش‌های من",
    }:
        return "orders"
    if _ORDER_READ_ACTION.fullmatch(action):
        return "order_detail"
    if action == "shop:faq" or text == "/faq":
        return "faq"
    if text == "/cancel":
        return "cancel"
    if action or not text or text.startswith("/"):
        return None
    from models.shop_customer_navigation import ShopCustomerChatState

    state = await db.get(ShopCustomerChatState, (context.bot_id, event.user_id))
    if (
        state is None or state.store_id != context.store_id
        or state.action != "ticket_input"
    ):
        return None
    expiry = state.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return "support" if expiry > datetime.now(UTC) else None


async def paused_customer_reply(
    db, *, context: BotContext, event: InboundEvent,
) -> BotReply | None:
    """Serve one exact after-sale route without entering shopping handlers.

    Registry receivers call this only after their effective
    operation gate permits paused/maintenance service. Disabled/revoked
    contexts and unrelated free text never gain a prefix-based bypass.
    """
    if context.status not in {"active", "paused", "maintenance"}:
        return None
    route = await _paused_service_route(db, context, event)
    if route is None:
        return None
    refund_request = bool(_REFUND_ACTION.fullmatch(event.callback_data or ""))
    if await is_blocked(
        db, bot_id=context.bot_id, platform=context.platform,
        platform_user_id=event.user_id,
    ) and not refund_request:
        return None
    await clear_pending_on_navigation(db, context=context, event=event)
    if route == "faq":
        return await CatalogFlow(bot_context=context)._settings_text(
            db, key="faq", platform=context.platform.value,
        )
    flow = {
        "support": CustomerSupportFlow,
        "orders": ShopOrdersFlow,
        "order_detail": CustomerExperienceFlow,
        "cancel": CustomerExperienceFlow,
    }[route](bot_context=context)
    return await flow.reply(event, db)


async def _send(
    context: BotContext, client, chat_id: int, reply: BotReply,
    *, event: InboundEvent | None = None,
) -> None:
    """Send one finalized message through only the current bot's transport."""
    from models.shop_customer_navigation import (
        ShopCustomerChatState, ShopCustomerMediaReceipt,
    )

    state = None
    previous = None
    if event is not None:
        async with session_maker() as db:
            state = await db.get(
                ShopCustomerChatState, (context.bot_id, event.user_id),
            )
            if state is not None:
                previous = state.ui_message_id
    if event is not None and (
        (event.text or "").split(" ", 1)[0] == "/start"
        or event.contact_phone is not None
        or (
            state is not None and state.action == "idle"
            and (event.text or "").strip() == "📱 اشتراک شمارهٔ تماس"
        )
    ):
        reply = replace(reply, show_main_keyboard=True)
    if event is not None and reply.attachments:
        transport = (
            TelegramTransport(client, bot_id=context.bot_id)
            if context.platform == Platform.TELEGRAM else client
        )
        for attachment in reply.attachments:
            key = (context.bot_id, event.user_id, attachment.storage_key)
            async with session_maker() as db:
                receipt = await db.get(ShopCustomerMediaReceipt, key)
                if receipt is not None and receipt.store_id != context.store_id:
                    raise ValueError("Customer media ownership mismatch.")
            # A receipt records the latest delivery, not permission to skip a
            # customer's explicit request for this file again.
            message_id = await transport.send_media(chat_id, attachment)
            if type(message_id) is int and message_id > 0:
                async with session_maker() as db:
                    stored = await db.get(ShopCustomerMediaReceipt, key)
                    if stored is not None:
                        if stored.store_id != context.store_id:
                            raise ValueError("Customer media ownership mismatch.")
                        stored.message_id = message_id
                    else:
                        db.add(ShopCustomerMediaReceipt(
                            bot_id=context.bot_id,
                            platform_user_id=event.user_id,
                            storage_key=attachment.storage_key,
                            store_id=context.store_id,
                            message_id=message_id,
                        ))
                    await db.commit()
        reply = replace(reply, attachments=())
    edit_id = previous or (event.message_id if event and event.is_callback else None)
    new_event = bool(
        event and (event.callback_data or "").startswith((
            "shop:place:", "shop:creditconfirm:", "shop:refundorder:",
        ))
    )
    if new_event and edit_id:
        transport = (
            TelegramTransport(client, bot_id=context.bot_id)
            if context.platform == Platform.TELEGRAM else client
        )
        if hasattr(transport, "clear_inline"):
            await transport.clear_inline(chat_id, edit_id)
        edit_id = None
    if context.platform == Platform.TELEGRAM:
        transport = TelegramTransport(client, bot_id=context.bot_id)
        result = await transport.send(
            chat_id, reply, edit_message_id=edit_id,
        )
    else:
        result = (
            await client.send(chat_id, reply, edit_message_id=edit_id)
            if edit_id else await client.send(chat_id, reply)
        )
    if event is not None and type(result) is int and result > 0:
        async with session_maker() as db:
            current = await db.get(
                ShopCustomerChatState, (context.bot_id, event.user_id),
                with_for_update=True,
            )
            if current is None:
                current = ShopCustomerChatState(
                    bot_id=context.bot_id, platform_user_id=event.user_id,
                    store_id=context.store_id, expires_at=datetime.now(UTC) + timedelta(days=7),
                )
                db.add(current)
            if current.store_id != context.store_id:
                raise ValueError("Customer UI ownership mismatch.")
            current.ui_message_id = result
            await db.commit()


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
        try:
            async with session_maker() as notice_db:
                # Immediate confirmation and a later worker share the exact
                # durable claim. An absent/final claim has no direct fallback;
                # a timeout stays quarantined rather than being sent again.
                transport = (
                    TelegramTransport(client, bot_id=context.bot_id)
                    if context.platform == Platform.TELEGRAM else client
                )
                await deliver_order_paid_once(
                    notice_db, order_id=order.id, bot_id=context.bot_id,
                    transport=transport,
                )
        except Exception:  # noqa: BLE001 - settlement is already committed
            LOG.warning(
                "Post-settlement notice needs review; order_id=%s bot_id=%s",
                order.id, context.bot_id,
            )
        if order.status == "paid":
            try:
                async with session_maker() as reward_db:
                    await ShopReferralService.award_for_paid_order(
                        reward_db, order.id,
                    )
            except Exception:  # noqa: BLE001 - referral cannot undo settlement
                LOG.warning(
                    "Post-settlement referral needs review; order_id=%s",
                    order.id,
                )
    return {"status": "settled" if changed else "already_settled"}


async def dispatch(
    context: BotContext, client, payload: Mapping, *, runtime_checked: bool = False,
) -> dict:
    """Process one uniquely claimed provider update and return a safe status."""
    if not isinstance(payload, Mapping):
        raise ValueError("Provider payload must be an object")  # noqa: TRY004
    if isinstance(payload.get("pre_checkout_query"), dict):
        return await _pre_checkout(context, client, payload)
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(
        message.get("successful_payment"), dict,
    ):
        return await _settle(context, client, payload)

    if not runtime_checked:
        runtime = await try_ingress(context, payload, client=client)
        if runtime.get("handled"):
            return runtime

    event = normalize_update(context.platform, payload)
    if event is None:
        return {"status": "ignored"}
    if event.callback_query_id:
        await _acknowledge(context, client, event.callback_query_id)
    if event.is_callback and event.message_id is not None:
        from models.shop_customer_navigation import ShopCustomerChatState

        async with session_maker() as db:
            state = await db.get(
                ShopCustomerChatState, (context.bot_id, event.user_id),
            )
            if state is not None and state.ui_message_id is not None and (
                state.ui_message_id != event.message_id
            ):
                # A stale callback may mutate the cart or place an order;
                # never execute it after the active screen has moved on.
                transport = (
                    TelegramTransport(client, bot_id=context.bot_id)
                    if context.platform == Platform.TELEGRAM else client
                )
                if hasattr(transport, "clear_inline"):
                    await transport.clear_inline(event.chat_id, event.message_id)
                return {"status": "stale_callback"}

    # A customer may request a refund on a paid order while shopping is off.
    refund_request = bool(_REFUND_ACTION.fullmatch(event.callback_data or ""))
    async with session_maker() as db:
        paused_route = None
        if context.status != "active":
            # Settlement is handled above this gate. Ordinary requests on a
            # disabled/revoked runtime never gain a support-prefix bypass.
            if context.status not in {"paused", "maintenance"}:
                return {"status": "disabled"}
            paused_route = await _paused_service_route(db, context, event)
        if context.status != "active" and paused_route is None:
            from models.shop_bot_operations import ShopBotOperations

            options = await db.get(ShopBotOperations, context.bot_id)
            note = (
                options.maintenance_message
                if options and options.maintenance_message
                else "فروشگاه موقتاً در حال نگهداری است."
            )
            await _send(context, client, event.chat_id, BotReply(note))
            return {"status": "maintenance"}

        if context.status == "active" and not refund_request:
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

        from models.shop_customer_navigation import ShopCustomerChatState

        active_state = await db.get(
            ShopCustomerChatState, (context.bot_id, event.user_id),
        )
        restore_keyboard = bool(
            active_state is not None
            and active_state.action == "phone_verification"
            and event.contact_phone is None
            and (
                event.callback_data is not None
                or should_clear_chat_state(
                    event.callback_data or "", (event.text or "").strip(),
                )
                or (event.text or "").strip() == "/cancel"
            )
        )
        await clear_pending_on_navigation(
            db, context=context, event=event,
        )
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

        flows = () if paused_route else (
            ShopOrdersFlow(bot_context=context),
        ) if refund_request else (
            ShopEngagementFlow(bot_context=context),
            ShopOrdersFlow(bot_context=context),
            ShopCartFlow(bot_context=context),
            CustomerExperienceFlow(bot_context=context),
            CatalogFlow(bot_context=context),
        )
        reply = (
            await paused_customer_reply(db, context=context, event=event)
            if paused_route else None
        )
        for flow in flows:
            reply = await flow.reply(event, db)
            if reply is not None:
                break
    if reply is None:
        return {"status": "ignored"}
    if restore_keyboard:
        reply = replace(reply, show_main_keyboard=True)
    await _send(context, client, event.chat_id, reply, event=event)
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
