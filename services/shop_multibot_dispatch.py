"""Shared Telegram/Bale multi-bot commerce dispatcher with verified BotContext.

The HTTP route and polling supervisor authenticate the Bot API credential
before constructing this context. No callback or message body may select an
arbitrary bot ID. Every operation resolves customer/credit/order scope from
that server-provided identity, and settlement runs before maintenance gates.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from sqlalchemy import select

from channels.contracts import (
    BotReply, InboundEvent, InlineAction, Platform, ReplyPurpose,
    ViewOutcome, ViewResult, normalize_update,
)
from channels.shop_payment_dispatch import send_order_invoice
from channels.telegram import TelegramTransport
from db import session_maker
from services.shop_bale_payments import (
    settle_bale_payment,
    validate_bale_precheckout,
)
from models.shop_content import ShopOrder
from models.shop_customer_navigation import ShopCustomerChatState, ShopCustomerMediaReceipt
from services.shop_admin_security import SecurityRejected
from services.shop_bot_context import BotContext, resolve_bot_context
from services.shop_cart import ShopCartFlow
from services.shop_channel_catalog import CatalogFlow, is_gallery_read_action
from services.shop_customer_experience import (
    CustomerExperienceFlow,
    clear_pending_on_navigation,
    should_clear_chat_state,
)
from services.shop_customer_notification_dispatch import deliver_order_paid_once
from services.shop_customer_support import CustomerSupportFlow, is_support_action
from services.shop_customer_views import (
    ChatBusy, active_view, consume, envelope, guarded_chat, persist,
    prepare_reply, resolve_action,
)
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_identity import is_blocked, register_customer
from services.shop_orders import ORDER_PAGE, ShopOrdersFlow
from services.shop_payments import PaymentRejected, ShopPaymentService
from services.shop_referrals import ShopReferralService
from services.shop_runtime.ingress import suspend_for_commerce, try_ingress

LOG = logging.getLogger(__name__)
_REFUND_ACTION = re.compile(r"shop:refundorder:([1-9][0-9]{0,18})\Z")
_ORDER_READ_ACTION = re.compile(r"ux:order:(detail|track):([1-9][0-9]{0,18})\Z")
_LEGACY_PRODUCT = re.compile(r"shop:item:[1-9][0-9]{0,18}\Z")
_LEGACY_TICKET = re.compile(r"ux:ticket:view:[1-9][0-9]{0,18}\Z")
_LEGACY_READS = {"shop:home", "shop:orders", "ux:support", "ux:tickets", "shop:faq"}


def _legacy_read(action: str) -> bool:
    """Keep old published cards and scoped receipt reads accessible."""
    return (
        action in _LEGACY_READS or is_gallery_read_action(action)
        or bool(_ORDER_READ_ACTION.fullmatch(action) or _LEGACY_PRODUCT.fullmatch(action)
                or _LEGACY_TICKET.fullmatch(action))
    )


def _view_read(action: str) -> bool:
    """Allow a truly unchanged read view to keep its current generation."""
    return _legacy_read(action) or action.startswith((
        "shop:list:", "shop:detail:", "shop:category:", "shop:categories:",
        "shop:files:", "shop:reviews:", "shop:orders:page:", "shop:cart:page:",
        "ux:terms:", "shop:checkout:",
    ))


async def _paused_service_route(db, context: BotContext, event: InboundEvent) -> str | None:
    """Allow only bounded after-sale help while cart and payment entry stay gated."""
    action = event.callback_data or ""
    text = (event.text or "").strip()
    if is_support_action(action) or text in {
        "/support", "/paysupport", "/ticket", "🆘 پشتیبانی", "💬 پشتیبانی",
    }:
        return "support"
    if action == "shop:orders" or ORDER_PAGE.fullmatch(action) or _REFUND_ACTION.fullmatch(action) or text in {
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
    *, event: InboundEvent | None = None, db=None, lease_check=None,
    recovery: bool = False,
) -> None:
    """Publish a scoped view only after a definite provider outcome."""
    transport = (
        TelegramTransport(client, bot_id=context.bot_id)
        if context.platform == Platform.TELEGRAM else client
    )
    if event is None:
        await transport.send(chat_id, reply)
        return
    if db is None:
        async with guarded_chat(session_maker, context.owner_key(event.user_id)) as guarded:
            await _send(
                context, client, chat_id, reply, event=event, db=guarded,
                lease_check=lease_check, recovery=recovery,
            )
        return

    key = context.owner_key(event.user_id)
    state = await db.get(ShopCustomerChatState, key)
    if state is None:
        state = ShopCustomerChatState(
            bot_id=context.bot_id, platform_user_id=event.user_id,
            store_id=context.store_id, expires_at=datetime.now(UTC),
        )
        db.add(state)
    if state.store_id != context.store_id:
        raise ValueError("Customer UI ownership mismatch.")
    if (
        (event.text or "").split(" ", 1)[0] == "/start"
        or event.contact_phone is not None
        or (state.action == "idle" and (event.text or "").strip() == "📱 اشتراک شمارهٔ تماس")
    ) and not reply.request_contact:
        reply = replace(reply, show_main_keyboard=True)

    data = envelope(state)
    if recovery and data.get("recovery"):
        if data["recovery"] != "confirmed" or active_view(state) is not None:
            return
    if data.get("pending"):
        # A process may have lost its lease after the provider accepted an edit.
        data["quarantine"] = state.ui_message_id
        data.pop("pending", None)
        data.pop("active", None)
        state.ui_message_id = None
        persist(state, data)
        await db.commit()

    for attachment in reply.attachments:
        receipt_key = (*key, attachment.storage_key)
        receipt = await db.get(ShopCustomerMediaReceipt, receipt_key)
        if receipt is not None and receipt.store_id != context.store_id:
            raise ValueError("Customer media ownership mismatch.")
        await db.commit()
        async with asyncio.timeout(12):
            message_id = await transport.send_media(chat_id, attachment)
        if type(message_id) is int and message_id > 0:
            if receipt is None:
                db.add(ShopCustomerMediaReceipt(
                    bot_id=context.bot_id, platform_user_id=event.user_id,
                    storage_key=attachment.storage_key, store_id=context.store_id,
                    message_id=message_id,
                ))
            else:
                receipt.message_id = message_id
            await db.commit()
    reply = replace(reply, attachments=())

    durable = reply.purpose == ReplyPurpose.DURABLE or (event.callback_data or "").startswith(
        "shop:creditconfirm:"
    )
    if durable or reply.request_contact or reply.purpose in {ReplyPurpose.MEDIA, ReplyPurpose.CONTACT}:
        previous = state.ui_message_id if data.get("active") else None
        consume(state)
        await db.commit()
        async with asyncio.timeout(12):
            await transport.send_view(chat_id, reply)
        await _retire(transport, chat_id, previous)
        return

    encoded, view = prepare_reply(reply)
    prior = active_view(state)
    if prior is not None and prior.get("signature") == view["signature"] and not reply.cards:
        return
    previous = state.ui_message_id if data.get("active") else None
    if recovery:
        data["recovery"] = "pending"
    else:
        data.pop("recovery", None)
    token = view["generation"]
    data["pending"] = token
    persist(state, data)
    await db.commit()

    try:
        async with asyncio.timeout(12):
            outcome = await transport.send_view(chat_id, encoded, edit_message_id=previous)
            if outcome.outcome == ViewOutcome.CANNOT_EDIT and previous is not None:
                outcome = await transport.send_view(chat_id, encoded)
    except TimeoutError:
        outcome = ViewResult(ViewOutcome.UNKNOWN)

    if lease_check is not None:
        await lease_check()
    current = await db.get(ShopCustomerChatState, key)
    if current is None or current.store_id != context.store_id:
        return
    data = envelope(current)
    if data.get("pending") != token:
        return
    data.pop("pending")
    confirmed = (
        outcome.outcome == ViewOutcome.CONFIRMED
        and type(outcome.message_id) is int and outcome.message_id > 0
    )
    if confirmed:
        current.ui_message_id = outcome.message_id
        data["active"] = view
        if recovery:
            data["recovery"] = "confirmed"
    elif outcome.outcome == ViewOutcome.NO_CHANGE and prior is not None:
        # The provider did not accept the new markup, so retain the known generation.
        data["active"] = prior
    elif outcome.outcome != ViewOutcome.REJECTED:
        data["quarantine"] = previous
        data.pop("active", None)
        current.ui_message_id = None
        # Repeated taps cannot replay an uncertain operation.
        data["recovery"] = "unknown"
    persist(current, data)
    await db.commit()
    if confirmed and previous != outcome.message_id:
        await _retire(transport, chat_id, previous)


async def _retire(transport, chat_id: int, message_id: int | None) -> None:
    """Remove controls best effort after the backend made them inert."""
    if message_id is None or not hasattr(transport, "clear_inline"):
        return
    try:
        async with asyncio.timeout(2):
            await transport.clear_inline(chat_id, message_id)
    except Exception:
        LOG.debug("Unable to retire obsolete commerce markup")


async def _acknowledge(context: BotContext, client, query_id: str) -> None:
    """Acknowledge a supported callback without interrupting processing."""
    try:
        async with asyncio.timeout(2):
            if context.platform == Platform.TELEGRAM:
                await client.answer_callback_query(
                    callback_query_id=query_id, cache_time=0,
                )
            else:
                await client.acknowledge(query_id)
    except Exception:
        LOG.debug("Commerce callback acknowledgement unavailable")


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
    lease_check=None,
) -> dict:
    """Process one uniquely claimed provider update and return a safe status."""
    if not isinstance(payload, Mapping):
        raise ValueError("Provider payload must be an object")
    if isinstance(payload.get("pre_checkout_query"), dict):
        return await _pre_checkout(context, client, payload)
    message = payload.get("message")
    if isinstance(message, dict) and isinstance(message.get("successful_payment"), dict):
        return await _settle(context, client, payload)
    if not runtime_checked:
        runtime = await try_ingress(context, payload, client=client)
        if runtime.get("handled"):
            return runtime

    event = normalize_update(context.platform, payload)
    if event is None or event.user_id != event.chat_id:
        return {"status": "ignored"}
    if event.callback_query_id:
        await _acknowledge(context, client, event.callback_query_id)
    try:
        async with guarded_chat(session_maker, context.owner_key(event.user_id)) as db:
            if lease_check is not None:
                await lease_check()
            try:
                current = await resolve_bot_context(
                    db, authenticated_bot_id=context.bot_id,
                    authenticated_platform=context.platform,
                    authenticated_provider_bot_id=context.provider_bot_id,
                    allow_settlement=True,
                )
            except SecurityRejected:
                return {"status": "disabled"}
            if current.store_id != context.store_id or (
                current.credential_version != context.credential_version
            ):
                return {"status": "disabled"}
            if context.status != "active" and current.status == "active":
                current = replace(current, status=context.status)
            if current.status not in {"active", "paused", "maintenance"}:
                return {"status": "disabled"}
            return await _dispatch_chat(db, current, client, event, payload, lease_check)
    except ChatBusy:
        return {"status": "conversation_busy"}


async def _dispatch_chat(db, context, client, event, payload, lease_check) -> dict:
    """Authorize a live action before touching account, workflow, or form state."""
    state = await db.get(ShopCustomerChatState, context.owner_key(event.user_id))
    if state is not None and state.store_id != context.store_id:
        return {"status": "blocked"}
    logical = None
    legacy = False
    if event.is_callback:
        data = event.callback_data or ""
        logical = resolve_action(state, data, event.message_id)
        legacy = logical is None and _legacy_read(data)
        if legacy:
            logical = data

    blocked = await is_blocked(
        db, bot_id=context.bot_id, platform=context.platform,
        platform_user_id=event.user_id,
    )
    refund = bool(logical and _REFUND_ACTION.fullmatch(logical))
    old_refund = _REFUND_ACTION.fullmatch(event.callback_data or "") if logical is None else None
    if old_refund and await _offer_refund_recovery(
        db, context, client, event, int(old_refund[1]), lease_check,
    ):
        return {"status": "stale_callback"}
    if blocked and not refund:
        return {"status": "blocked"}
    if event.is_callback and logical is None:
        await _recover(db, context, client, event, state, lease_check)
        return {"status": "stale_callback"}
    if logical is not None:
        event = replace(event, callback_data=logical)
    paused_route = None
    if context.status != "active":
        paused_route = await _paused_service_route(db, context, event)
        if paused_route is None:
            from models.shop_bot_operations import ShopBotOperations

            options = await db.get(ShopBotOperations, context.bot_id)
            note = options.maintenance_message if options else None
            await db.commit()
            await _send(
                context, client, event.chat_id,
                BotReply(note or "فروشگاه موقتاً در حال نگهداری است."),
            )
            return {"status": "maintenance"}

    if logical is not None and not legacy and not _view_read(logical) and state is not None:
        consume(state)
        await db.commit()
    if context.status == "active" and not refund and not legacy:
        await register_customer(
            db, bot_id=context.bot_id, platform=context.platform,
            platform_user_id=event.user_id,
            username=_user_name(payload), first_name=_first_name(payload),
        )
    if logical is not None and not blocked:
        await suspend_for_commerce(db, context, event.user_id)

    restore_keyboard = bool(
        state is not None and state.action == "phone_verification"
        and event.contact_phone is None
        and (
            event.is_callback or should_clear_chat_state("", (event.text or "").strip())
            or (event.text or "").strip() == "/cancel"
        )
    )
    await clear_pending_on_navigation(db, context=context, event=event)
    if logical and logical.startswith("shop:pay:"):
        try:
            await send_order_invoice(
                db, platform=context.platform, user_id=event.user_id, bot_id=context.bot_id,
                order_id=int(logical.removeprefix("shop:pay:")),
                telegram_bot=client if context.platform == Platform.TELEGRAM else None,
                bale_transport=client if context.platform == Platform.BALE else None,
            )
        except (PaymentRejected, ValueError):
            await db.rollback()
            await _send(
                context, client, event.chat_id, BotReply(
                    "آماده‌سازی پرداخت انجام نشد. وضعیت را از سفارش‌های من بررسی کنید.",
                    ((InlineAction("سفارش‌های من", "shop:orders"),),),
                ), event=event, db=db, lease_check=lease_check,
            )
        return {"status": "invoice_requested"}

    if paused_route:
        reply = await paused_customer_reply(db, context=context, event=event)
    else:
        flows = (ShopOrdersFlow,) if refund else (
            ShopEngagementFlow, ShopOrdersFlow, ShopCartFlow, CustomerExperienceFlow, CatalogFlow,
        )
        reply = None
        for flow in flows:
            reply = await flow(bot_context=context).reply(event, db)
            if reply is not None:
                break
    # Domain flows own their commits. Discard any staged, uncommitted changes
    # before the view reservation commits on this same advisory-lock session.
    await db.rollback()
    if reply is None:
        return {"status": "ignored"}
    if restore_keyboard and not reply.request_contact:
        reply = replace(reply, show_main_keyboard=True)
    await _send(context, client, event.chat_id, reply, event=event, db=db, lease_check=lease_check)
    return {"status": "processed"}


async def _recover(db, context, client, event, state, lease_check) -> None:
    """Offer one actionable view without invoking the obsolete action."""
    if state is not None:
        current = active_view(state)
        if current and current["actions"] and event.message_id == state.ui_message_id:
            # A shopper who tapped this message already has the current controls.
            return
    rows = (
        ((InlineAction("منوی اصلی", "shop:home"),),)
        if context.status == "active" else
        ((InlineAction("سفارش‌های من", "shop:orders"), InlineAction("پشتیبانی", "ux:support")),)
    )
    await _send(
        context, client, event.chat_id,
        BotReply("این دکمه دیگر فعال نیست. از گزینه‌های زیر ادامه دهید.", rows),
        event=event, db=db, lease_check=lease_check, recovery=True,
    )


async def _offer_refund_recovery(db, context, client, event, order_id, lease_check) -> bool:
    """Restore the exact owned paid-order route without executing its old control."""
    owned = await db.scalar(select(ShopOrder.id).where(
        ShopOrder.id == order_id,
        ShopOrder.store_id == context.store_id,
        ShopOrder.bot_id == context.bot_id,
        ShopOrder.platform == context.platform.value,
        ShopOrder.platform_user_id == event.user_id,
        ShopOrder.status.in_(("paid", "paid_unfulfilled")),
    ))
    if owned is None:
        return False
    await _send(
        context, client, event.chat_id,
        BotReply(
            f"این دکمه دیگر فعال نیست. می‌توانید درخواست بازپرداخت سفارش #{order_id} را ثبت کنید.",
            ((InlineAction("درخواست بازپرداخت", f"shop:refundorder:{order_id}"),),),
        ),
        event=event, db=db, lease_check=lease_check, recovery=True,
    )
    return True


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
