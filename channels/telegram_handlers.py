"""A thin Aiogram router for the shared product catalog.

Legacy checkout handlers remain unchanged until the order model is migrated.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from sqlalchemy import select, or_
from datetime import datetime, timezone

from db import get_db_session
from models.shop_checkout import ShopCart, ShopCartInputSession
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_multibot import LEGACY_TELEGRAM_BOT_ID
from aiogram.types import CallbackQuery, Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, Platform
from channels.telegram import TelegramTransport
from services.shop_channel_catalog import CatalogFlow
from services.shop_customer_experience import (
    CustomerExperienceFlow, clear_pending_on_navigation,
)
from services.shop_bot_context import resolve_legacy_bot_context
from services.shop_cart import ShopCartFlow
from services.shop_bot_profiles import get_bot_options
from services.shop_bot_operations import legacy_state
from services.shop_customer_notification_dispatch import deliver_order_paid_once
from services.shop_multibot_dispatch import paused_customer_reply
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_referrals import ShopReferralService
from services.shop_orders import ShopOrdersFlow
from services.shop_identity import is_blocked, register_customer
from channels.shop_payment_dispatch import send_order_invoice
from services.shop_payments import PaymentRejected, ShopPaymentService
import config


shop_catalog_router = Router(name="shop_catalog")


class AwaitingShopInput(BaseFilter):
    """Match free-form text only while a known shopping form is awaiting it."""

    async def __call__(self, message: Message) -> bool:
        """Do not intercept unrelated legacy Telegram chat messages."""
        if (
            message.from_user is None or message.chat.type != "private"
            or not message.text or message.text.startswith("/")
        ):
            return False
        async with get_db_session() as session:
            cart_pending = await session.scalar(select(ShopCart.id).where(
                ShopCart.bot_id == LEGACY_TELEGRAM_BOT_ID,
                ShopCart.platform_user_id == message.from_user.id,
                ShopCart.awaiting_input.is_not(None),
            ).limit(1))
            if cart_pending is not None:
                return True
            shared_input = await session.scalar(
                select(ShopCartInputSession.cart_id).where(
                    ShopCartInputSession.bot_id == LEGACY_TELEGRAM_BOT_ID,
                    ShopCartInputSession.platform_user_id == message.from_user.id,
                    ShopCartInputSession.awaiting_input.is_not(None),
                ).limit(1)
            )
            if shared_input is not None:
                return True
            chat_state = await session.get(
                ShopCustomerChatState,
                (LEGACY_TELEGRAM_BOT_ID, message.from_user.id),
            )
            return bool(
                chat_state is not None and chat_state.action in {
                    "product_search", "address_input", "ticket_input",
                    "phone_verification",
                }
                and (
                    chat_state.expires_at.replace(tzinfo=timezone.utc)
                    if chat_state.expires_at.tzinfo is None
                    else chat_state.expires_at
                ) > datetime.now(timezone.utc)
            )


async def _shop_reply(
    event: InboundEvent, session: AsyncSession
) -> BotReply | None:
    """Select the common cart first, then catalog for non-cart actions."""
    status = await legacy_state(session, event.platform.value)
    if status.state == "disabled":
        return None
    options = await get_bot_options(session, event.platform.value)
    context = await resolve_legacy_bot_context(
        session, authenticated_platform=event.platform,
    )
    if status.state in {"paused", "maintenance"} or options.maintenance_enabled:
        reply = await paused_customer_reply(session, context=context, event=event)
        return reply or BotReply(status.message)
    await clear_pending_on_navigation(
        session, context=context, event=event,
    )
    engagement = await ShopEngagementFlow(
        config.SHOP_DISPLAY_UNIT
    ).reply(event, session)
    if engagement is not None:
        return engagement
    orders = await ShopOrdersFlow(config.SHOP_DISPLAY_UNIT).reply(event, session)
    if orders is not None:
        return orders
    cart = await ShopCartFlow(config.SHOP_DISPLAY_UNIT).reply(event, session)
    if cart is not None:
        return cart
    unified = await CustomerExperienceFlow().reply(event, session)
    if unified is not None:
        return unified
    return await _flow().reply(event, session)


def _flow() -> CatalogFlow:
    """Build a shared catalog controller using configured currency display."""
    return CatalogFlow(
        currency_label=config.SHOP_CURRENCY_LABEL,
        display_unit=config.SHOP_DISPLAY_UNIT,
    )


@shop_catalog_router.message(
    Command("wallet", "referral", "ref", "subscribe", "unsubscribe", "linkstart", "linkconfirm", "linkapprove", "linkcancel")
)
@shop_catalog_router.message(F.text.in_({
    "💳 اعتبار من", "🎁 معرفی دوستان",
    "📣 دریافت اطلاعیه", "🔕 لغو اطلاعیه",
}))
async def engagement_message(
    message: Message, session: AsyncSession
) -> None:
    """Use one shared entitlement and consent flow on Telegram."""
    if message.from_user is None or message.chat.type != "private":
        return
    await register_customer(
        session,
        platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    if await is_blocked(
        session,
        platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
    ):
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(event.chat_id, reply)


@shop_catalog_router.message(Command("orders"))
@shop_catalog_router.message(F.text == "📦 سفارش‌های من")
async def show_shop_orders(message: Message, session: AsyncSession) -> None:
    """Show new shared orders belonging to this Telegram account only."""
    if message.from_user is None or message.chat.type != "private":
        return
    reply = await _shop_reply(
        InboundEvent(
            platform=Platform.TELEGRAM,
            chat_id=message.chat.id,
            user_id=message.from_user.id,
            text="/orders",
        ),
        session,
    )
    if reply is not None:
        await TelegramTransport(message.bot).send(message.chat.id, reply)


@shop_catalog_router.message(Command("cart"))
@shop_catalog_router.message(Command("checkout"))
@shop_catalog_router.message(F.text == "🛒 سبد خرید")
@shop_catalog_router.message(AwaitingShopInput())
async def shopping_basket_text(message: Message, session: AsyncSession) -> None:
    """Process shopping commands and the next address/coupon text message."""
    if message.from_user is None or message.chat.type != "private":
        return
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
    ):
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text=message.text,
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(message.chat.id, reply)


@shop_catalog_router.message(
    Command(
        "menu", "search", "account", "support", "paysupport",
        "terms", "ticket", "address", "wishlist", "profile", "cancel",
    )
)
@shop_catalog_router.message(F.text.in_({
    "🔎 جستجوی محصول", "👤 حساب من", "🆘 پشتیبانی", "🏠 منوی اصلی",
}))
async def unified_customer_message(
    message: Message, session: AsyncSession,
) -> None:
    """Use the same customer business router as Bale and registry bots."""
    if message.from_user is None or message.chat.type != "private":
        return
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
    ):
        return
    await register_customer(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id, user_id=message.from_user.id,
        text=message.text,
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(event.chat_id, reply)


@shop_catalog_router.message(F.contact)
async def verified_customer_contact(
    message: Message, session: AsyncSession,
) -> None:
    """Only Contact.user_id == message sender ID can verify a phone."""
    if (
        message.from_user is None or message.chat.type != "private"
        or message.contact is None
    ):
        return
    await register_customer(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id, user_id=message.from_user.id,
        contact_phone=message.contact.phone_number,
        contact_user_id=message.contact.user_id,
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(event.chat_id, reply)


@shop_catalog_router.message(Command("catalog"))
@shop_catalog_router.message(F.text.in_({"🛍 محصولات", "🏠 صفحه اول"}))
async def show_shop_catalog(message: Message, session: AsyncSession) -> None:
    """Open the same published catalog shown by the Bale adapter."""
    # Keep the storefront private, matching Bale's event normalization.
    if message.from_user is None or message.chat.type != "private":
        return
    await register_customer(
        session,
        platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
    )
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=message.from_user.id
    ):
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        text="🛍 محصولات",
    )
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(message.bot).send(event.chat_id, reply)


@shop_catalog_router.pre_checkout_query()
async def shop_pre_checkout(query: PreCheckoutQuery) -> None:
    """Accept only a matching, unpaid, immutable Bot API invoice.

    No purchase is fulfilled at pre-checkout time. The actual receipt arrives
    later as a separate successful_payment message.
    """
    async with get_db_session() as session:
        accepted, reason = await ShopPaymentService.precheckout(
            session,
            platform=Platform.TELEGRAM,
            payer_id=query.from_user.id,
            payload=query.invoice_payload,
            currency=query.currency,
            amount=query.total_amount,
        )
    await query.answer(
        ok=accepted,
        error_message=reason if not accepted else None,
    )


@shop_catalog_router.message(F.successful_payment)
async def shop_successful_payment(message: Message) -> None:
    """Settle a verified Telegram payment once, never on invoice send."""
    payment = message.successful_payment
    if message.from_user is None or message.chat.type != "private":
        return
    async with get_db_session() as session:
        try:
            order, changed = await ShopPaymentService.settle(
                session,
                platform=Platform.TELEGRAM,
                payer_id=message.from_user.id,
                chat_id=message.chat.id,
                payload=payment.invoice_payload,
                currency=payment.currency,
                amount=payment.total_amount,
                charge_id=payment.telegram_payment_charge_id,
                provider_charge_id=payment.provider_payment_charge_id or None,
            )
        except PaymentRejected:
            # An already-settled external payment must be reconciled by a
            # human rather than silently discarded or fulfilled twice.
            raise
    if changed:
        import logging
        try:
            async with get_db_session() as notice_session:
                await deliver_order_paid_once(
                    notice_session, order_id=order.id,
                    bot_id=LEGACY_TELEGRAM_BOT_ID,
                    transport=TelegramTransport(
                        message.bot, bot_id=LEGACY_TELEGRAM_BOT_ID,
                    ),
                )
        except Exception:
            logging.warning(
                "Post-settlement notice needs review; order_id=%s bot_id=%s",
                order.id, LEGACY_TELEGRAM_BOT_ID,
            )
        # Paid settlement is already committed. Referral failures must not
        # roll back an external provider transaction.
        if order.status == "paid":
            try:
                async with get_db_session() as reward_session:
                    await ShopReferralService.award_for_paid_order(
                        reward_session, order.id
                    )
            except Exception:
                logging.exception(
                    "Referral reward processing failed for order ID %s",
                    order.id,
                )


# The shared customer experience uses the ux: namespace. Route both
# callback families through the SAME ownership-checked dispatcher.
@shop_catalog_router.callback_query(F.data.startswith("ux:"))
@shop_catalog_router.callback_query(F.data.startswith("shop:"))
async def shop_catalog_button(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Handle shop callbacks without sharing Aiogram objects with the core."""
    await callback.answer()
    if await is_blocked(
        session, platform=Platform.TELEGRAM,
        platform_user_id=callback.from_user.id
    ):
        return
    if callback.message is None or callback.message.chat.type != "private":
        return
    event = InboundEvent(
        platform=Platform.TELEGRAM,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        callback_data=callback.data,
        callback_query_id=callback.id,
    )
    if callback.data and callback.data.startswith("shop:pay:"):
        status = await legacy_state(session, Platform.TELEGRAM.value)
        options = await get_bot_options(session, Platform.TELEGRAM.value)
        if status.state != "active" or options.maintenance_enabled:
            reply = await _shop_reply(event, session)
            if reply is not None:
                await TelegramTransport(callback.bot).send(event.chat_id, reply)
            return
        try:
            order_id = int(callback.data.removeprefix("shop:pay:"))
            await send_order_invoice(
                session,
                platform=Platform.TELEGRAM,
                user_id=event.user_id,
                order_id=order_id,
                telegram_bot=callback.bot,
            )
        except (PaymentRejected, ValueError) as exc:
            await TelegramTransport(callback.bot).send(
                event.chat_id, BotReply(str(exc))
            )
        return
    reply = await _shop_reply(event, session)
    if reply is not None:
        await TelegramTransport(callback.bot).send(event.chat_id, reply)
