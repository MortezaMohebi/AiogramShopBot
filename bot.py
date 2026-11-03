import asyncio
import json
import logging
from contextlib import suppress
import sys
import os
from hmac import compare_digest

from aiohttp import ClientSession, ClientTimeout
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile, Update
from redis.asyncio import Redis
from dashboard.secure_admin import SecureShopAdmin as Admin
from dashboard.next_api import router as next_admin_router

import config
from aiogram import Dispatcher
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.staticfiles import StaticFiles

from admin import authentication_backend
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, Platform, normalize_update
from services.shop_channel_catalog import CatalogFlow
from services.shop_cart import ShopCartFlow
from services.shop_bot_profiles import get_bot_options
from services.shop_engagement_flow import ShopEngagementFlow
from services.shop_referrals import ShopReferralService
from services.bale_wallet import BaleWalletService, CheckoutRejected
from services.shop_bale_payments import (
    settle_bale_payment, validate_bale_precheckout,
)
from services.shop_payments import PaymentRejected
from channels.shop_payment_dispatch import send_order_invoice
from services.shop_orders import ShopOrdersFlow
from services.shop_identity import is_blocked, register_customer
from services.shop_updates import claim_update, finish_update
from dashboard.persian import localize_model_view
from dashboard.permissions import secure_model_view
from dashboard.wallet_views import ShopWalletAdjustmentView
from dashboard.campaign_views import ShopCampaignReviewView
from dashboard.campaign_media_views import (
    ShopCampaignMediaUploadView, ShopCampaignMediaPreviewView,
)
from dashboard.analytics_views import ShopAnalyticsView
from models.shop_staff import ShopStaffAdmin
from models.shop_delivery import ShopRemoteFileAdmin, ShopInboundUpdateAdmin
from models.shop_engagement import (
    ShopWalletAccountAdmin, ShopWalletEntryAdmin, ShopReferralPolicyAdmin,
    ShopReferralProfileAdmin, ShopReferralRewardAdmin,
    ShopCampaignAdmin, ShopCampaignDeliveryAdmin, ShopCampaignMediaAdmin,
    ShopBroadcastRateSlotAdmin, ShopCampaignAuditAdmin,
)
from dashboard.media_views import ShopMediaPreviewView, ShopUploadView
from dashboard.order_views import ShopOrderReviewView
from dashboard.refund_views import ShopRefundReviewView
from db import create_db_and_tables, engine, get_db_session
import uvicorn
from fastapi.responses import JSONResponse
from enums.cryptocurrency import Cryptocurrency
from models.shop_checkout import (
    ShopCartAdmin, ShopCartItemAdmin, ShopShippingMethodAdmin,
    ShopCouponAdmin, ShopOrderLineAdmin, ShopOrderReviewAuditAdmin,
)
from models.shop_payment import (
    ShopPaymentAttemptAdmin,
    ShopRefundCaseAdmin,
)
from models.shop_content import ProductAdmin, ProductMediaAdmin, ShopCategoryAdmin, ShopIdentityAdmin, ShopOrderAdmin, ShopSettingsAdmin, TestimonialAdmin
from models.buy import BuyAdmin
from models.buyItem import BuyItemAdmin
from models.cart import CartAdmin
from models.cartItem import CartItemAdmin
from models.category import CategoryAdmin
from models.coupon import CouponAdmin
from models.deposit import DepositAdmin
from models.item import ItemAdmin
from models.payment import PaymentAdmin
from models.referral import ReferralBonusAdmin
from models.review import ReviewAdmin
from models.shipping_option import ShippingOptionAdmin
from models.subcategory import SubcategoryAdmin
from models.user import UserAdmin
from processing.processing import processing_router
from repositories.button_media import ButtonMediaRepository
from services.media import MediaService
from services.notification import NotificationService
from services.wallet import WalletService
from utils.telegram import create_bot, create_telegram_session
from utils.telegram_rotating_session import RotatingTelegramSession
from services.shop_telegram_transport_control import load_verified_on_boot
from utils.utils import validate_i18n

redis = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD)
session = RotatingTelegramSession(create_telegram_session())
bot = create_bot(config.TOKEN, session)
dp = Dispatcher(storage=RedisStorage(redis))


async def _startup() -> None:
    await create_db_and_tables()
    # Load only the last verified encrypted outbound transport before *any*
    # Telegram Bot API call. Never fall back to a different route on failure.
    expected_bot_id = await load_verified_on_boot(bot)
    static = Path("static")
    if static.exists() is False:
        static.mkdir()
    # An inaccessible Proxy or Worker must not take down the admin panel:
    # the operator needs the panel to stage a verified recovery route.
    # A genuinely different authenticated Bot ID remains a hard failure.
    profile_available = False
    bot_photo_id = config.DEFAULT_MEDIA_FILE_ID
    try:
        me = await asyncio.wait_for(bot.get_me(), timeout=12)
        if expected_bot_id is not None and me.id != expected_bot_id:
            raise RuntimeError(
                "Configured Telegram token identifies a different verified bot."
            )
        profile_available = True
    except RuntimeError:
        raise
    except Exception:
        logging.warning(
            "Telegram API startup probe unavailable; admin recovery remains "
            "available, outbound messages may be interrupted."
        )
    if profile_available:
        try:
            photos = await asyncio.wait_for(
                bot.get_user_profile_photos(me.id), timeout=12,
            )
            if photos.total_count > 0:
                bot_photo_id = photos.photos[0][-1].file_id
        except Exception:
            logging.warning(
                "Telegram profile photo unavailable; using text fallback."
            )
    if not bot_photo_id:
        logging.warning(
            "Telegram bot has no profile photo; legacy photo-only "
            "navigation will be unavailable until configured."
        )
    with open("static/no_image.jpeg", "w") as destination:
        destination.write(bot_photo_id)
    if bot_photo_id and profile_available:
        await MediaService.update_inaccessible_media(bot)
    validate_i18n()
    if bot_photo_id and profile_available:
        await ButtonMediaRepository.init_buttons_media()
    if config.CRYPTO_FORWARDING_MODE:
        for cryptocurrency in Cryptocurrency:
            forwarding_address = cryptocurrency.get_forwarding_address()
            is_addr_valid = WalletService.validate_withdrawal_address(forwarding_address, cryptocurrency)
            if is_addr_valid is False:
                logging.error(
                    "Your withdrawal address for %s cryptocurrency is not configured correctly: %s",
                    cryptocurrency.name,
                    forwarding_address
                )
                sys.exit(1)
    for admin in config.ADMIN_ID_LIST:
        try:
            await bot.send_message(admin, 'Bot is working')
        except Exception:
            logging.warning("Telegram admin startup notification unavailable.")

    if config.TELEGRAM_UPDATE_MODE == "webhook" and (
        os.environ.get("CODESPACE_MANUAL_WEBHOOK") == "true"
    ):
        logging.info(
            "Codespaces webhook registration deferred until explicit connect."
        )
    elif config.TELEGRAM_UPDATE_MODE == "webhook":
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET_TOKEN,
            max_connections=2 if config.WEBHOOK_HOST.endswith(".app.github.dev") else 40,
        )
    else:
        # Telegram does not permit getUpdates while a webhook is active.
        await bot.delete_webhook(drop_pending_updates=False)
        app.state.telegram_polling_task = asyncio.create_task(
            dp.start_polling(
                bot,
                handle_signals=False,
                close_bot_session=False,
                polling_timeout=10,
            ),
            name="telegram-cloudflare-polling",
        )


async def _shutdown() -> None:
    logging.warning('Shutting down..')
    polling_task = getattr(app.state, "telegram_polling_task", None)
    if polling_task is not None:
        if not polling_task.done():
            polling_task.cancel()
        with suppress(asyncio.CancelledError):
            await polling_task
    elif os.environ.get("CODESPACE_MANUAL_WEBHOOK") != "true":
        await bot.delete_webhook()
    await dp.storage.close()
    await bot.session.close()
    logging.warning('Bye!')


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the Telegram bot and optional reusable Bale HTTP client."""
    if bool(config.BALE_BOT_TOKEN) != bool(config.BALE_WEBHOOK_SECRET):
        raise ValueError(
            "Configure BALE_BOT_TOKEN and BALE_WEBHOOK_SECRET together."
        )
    if config.BALE_BOT_TOKEN and len(config.BALE_WEBHOOK_SECRET) < 32:
        raise ValueError("BALE_WEBHOOK_SECRET must contain at least 32 characters.")

    bale_client = (
        ClientSession(timeout=ClientTimeout(total=15))
        if config.BALE_BOT_TOKEN
        else None
    )
    app.state.bale_http_client = bale_client
    started = False
    try:
        await _startup()
        started = True
        yield
    finally:
        try:
            if started:
                await _shutdown()
        finally:
            if bale_client is not None:
                await bale_client.close()


app = FastAPI(lifespan=lifespan)

@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Report live app database/Redis readiness to Docker only."""
    from sqlalchemy import text
    async with get_db_session() as session:
        await session.execute(text("SELECT 1"))
    if not await redis.ping():
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return {"ok": True, "runtime": "bot"}


# Signed Next.js BFF. SQLAdmin remains intact during migration.
app.include_router(next_admin_router)
app.state.telegram_bot = bot
app.mount(
    "/shop-assets",
    StaticFiles(directory=Path(__file__).resolve().parent / "assets"),
    name="shop-assets",
)
admin = Admin(
    app=app,
    engine=engine,
    authentication_backend=authentication_backend,
    title="مدیریت فروشگاه",
    templates_dir=str(Path(__file__).resolve().parent / "templates"),
)
admin.add_model_view(secure_model_view(localize_model_view(UserAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(BuyAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(ShippingOptionAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(CouponAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(CategoryAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(SubcategoryAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(ItemAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(DepositAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(BuyItemAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(PaymentAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(CartAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(CartItemAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(ReferralBonusAdmin)))
admin.add_model_view(secure_model_view(localize_model_view(ReviewAdmin)))
admin.add_model_view(secure_model_view(ShopSettingsAdmin))
admin.add_model_view(secure_model_view(ShopCategoryAdmin))
admin.add_model_view(secure_model_view(ProductAdmin))
admin.add_model_view(secure_model_view(ProductMediaAdmin))
admin.add_model_view(secure_model_view(TestimonialAdmin))
admin.add_model_view(secure_model_view(ShopIdentityAdmin))
admin.add_model_view(secure_model_view(ShopOrderAdmin))
admin.add_model_view(secure_model_view(ShopShippingMethodAdmin))
admin.add_model_view(secure_model_view(ShopCouponAdmin))
admin.add_model_view(secure_model_view(ShopCartAdmin))
admin.add_model_view(secure_model_view(ShopCartItemAdmin))
admin.add_model_view(secure_model_view(ShopOrderLineAdmin))
admin.add_model_view(secure_model_view(ShopOrderReviewAuditAdmin))
admin.add_model_view(secure_model_view(ShopPaymentAttemptAdmin))
admin.add_model_view(secure_model_view(ShopRefundCaseAdmin))
admin.add_view(ShopUploadView)
admin.add_view(ShopMediaPreviewView)
admin.add_view(ShopOrderReviewView)
admin.add_view(ShopRefundReviewView)
admin.add_view(ShopWalletAdjustmentView)
admin.add_view(ShopCampaignReviewView)
admin.add_view(ShopCampaignMediaUploadView)
admin.add_view(ShopCampaignMediaPreviewView)
admin.add_view(ShopAnalyticsView)
admin.add_model_view(secure_model_view(ShopStaffAdmin))
admin.add_model_view(secure_model_view(ShopWalletAccountAdmin))
admin.add_model_view(secure_model_view(ShopWalletEntryAdmin))
admin.add_model_view(secure_model_view(ShopReferralPolicyAdmin))
admin.add_model_view(secure_model_view(ShopReferralProfileAdmin))
admin.add_model_view(secure_model_view(ShopReferralRewardAdmin))
admin.add_model_view(secure_model_view(ShopCampaignAdmin))
admin.add_model_view(secure_model_view(ShopCampaignDeliveryAdmin))
admin.add_model_view(secure_model_view(ShopCampaignMediaAdmin))
admin.add_model_view(secure_model_view(ShopCampaignAuditAdmin))
admin.add_model_view(secure_model_view(ShopBroadcastRateSlotAdmin))
admin.add_model_view(secure_model_view(ShopRemoteFileAdmin))
admin.add_model_view(secure_model_view(ShopInboundUpdateAdmin))

app.include_router(processing_router)


@app.post("/webhooks/bale/{webhook_secret}")
async def bale_webhook(webhook_secret: str, request: Request):
    """Receive private Bale events with a secret URL and shared catalog logic.

    The supplied Bale snapshot does not document Telegram-style secret
    headers. Keep the path secret unguessable and redact it from proxy logs.
    """
    configured_secret = config.BALE_WEBHOOK_SECRET
    if (
        not config.BALE_BOT_TOKEN
        or not configured_secret
        or not compare_digest(webhook_secret, configured_secret)
    ):
        raise HTTPException(status_code=404, detail="Not found")

    raw = await request.body()
    if len(raw) > 256_000:
        raise HTTPException(status_code=413, detail="Payload too large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid update")

    # A unique update receipt is persisted before any outgoing Bot API send.
    update_id = payload.get("update_id")
    if type(update_id) is not int or update_id < 0:
        raise HTTPException(status_code=400, detail="Invalid update ID")
    fresh, state = await claim_update(
        platform=Platform.BALE, token=config.BALE_BOT_TOKEN,
        update_id=update_id,
    )
    if not fresh:
        return {"status": "duplicate", "receipt_state": state}
    try:
        response = await _process_bale_update(request, payload)
    except Exception:
        await finish_update(
            platform=Platform.BALE, token=config.BALE_BOT_TOKEN,
            update_id=update_id, success=False,
        )
        raise
    await finish_update(
        platform=Platform.BALE, token=config.BALE_BOT_TOKEN,
        update_id=update_id, success=True,
    )
    return response


async def _process_bale_update(request: Request, payload: dict):
    """Handle an already-claimed Bale update exactly once per bot."""

    transport = BaleTransport(
        config.BALE_BOT_TOKEN, request.app.state.bale_http_client
    )
    # Payment events must be consumed BEFORE generic message normalization.
    # Bale's successful_payment messages do not necessarily contain text.
    precheckout = payload.get("pre_checkout_query")
    if isinstance(precheckout, dict):
        query_id = precheckout.get("id")
        if not isinstance(query_id, str) or not query_id:
            raise HTTPException(status_code=400, detail="Invalid pre-checkout query")
        if not config.BALE_WALLET_CHECKOUT_ENABLED:
            accepted, reason = False, "پرداخت کیف پول در حال حاضر غیرفعال است."
        else:
            async with get_db_session() as session:
                accepted, reason = await validate_bale_precheckout(
                    session, precheckout
                )
        try:
            await transport.answer_pre_checkout(
                query_id,
                accepted=accepted,
                error_message=reason,
            )
        except BaleApiError:
            raise HTTPException(
                status_code=502, detail="Bale pre-checkout response failed"
            ) from None
        return {"status": "accepted" if accepted else "declined"}

    payment_message = payload.get("message")
    if isinstance(payment_message, dict) and isinstance(
        payment_message.get("successful_payment"), dict
    ):
        payer = payment_message.get("from")
        chat = payment_message.get("chat")
        if (
            not isinstance(payer, dict)
            or type(payer.get("id")) is not int
            or not isinstance(chat, dict)
            or chat.get("type") != "private"
            or type(chat.get("id")) is not int
        ):
            raise HTTPException(status_code=400, detail="Invalid payer")
        try:
            async with get_db_session() as session:
                # Blocked customers can pay a previously issued invoice;
                # reconcile the receipt instead of abandoning real funds.
                order, changed = await settle_bale_payment(
                    session,
                    transport,
                    payer_id=payer["id"],
                    chat_id=chat["id"],
                    payment=payment_message["successful_payment"],
                )
        except (CheckoutRejected, PaymentRejected):
            raise HTTPException(
                status_code=422, detail="Wallet receipt did not match order"
            ) from None
        except BaleApiError:
            raise HTTPException(
                status_code=502, detail="Bale payment inquiry unavailable"
            ) from None
        if changed:
            note = (
                f"✅ پرداخت سفارش #{order.id} تأیید شد."
                if order.status == "paid"
                else (
                    f"⚠️ پرداخت سفارش #{order.id} ثبت شد، اما موجودی نیاز به "
                    "بررسی فروشنده دارد. سفارش برای پیگیری نگه داشته شده است."
                )
            )
            try:
                await transport.send(chat["id"], BotReply(note))
            except BaleApiError:
                # Payment settlement is already durable. Retries are safe:
                # confirm_success will not deduct inventory twice.
                raise HTTPException(
                    status_code=502, detail="Payment notice delivery failed"
                ) from None
        if changed and order.status == "paid":
            # A referral error must not cause a successful payment to be
            # reported as a failed transfer or retried by the sender.
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
        return {"status": "processed" if changed else "already_processed"}

    event = normalize_update(Platform.BALE, payload)
    if event is None:
        return {"status": "ignored"}

    source = payload.get("callback_query") or payload.get("message") or {}
    customer = source.get("from") if isinstance(source, dict) else {}
    async with get_db_session() as session:
        await register_customer(
            session,
            platform=Platform.BALE,
            platform_user_id=event.user_id,
            username=customer.get("username") if isinstance(customer, dict) else None,
            first_name=customer.get("first_name") if isinstance(customer, dict) else None,
        )
        if await is_blocked(
            session, platform=Platform.BALE,
            platform_user_id=event.user_id,
        ):
            return {"status": "blocked"}
        options = await get_bot_options(session, Platform.BALE.value)
        if options.maintenance_enabled:
            if event.callback_query_id:
                await transport.acknowledge(event.callback_query_id)
            await transport.send(
                event.chat_id,
                BotReply("فروشگاه موقتاً در حالت نگهداری است. لطفاً بعداً مراجعه کنید."),
            )
            return {"status": "maintenance"}
        if event.callback_data and event.callback_data.startswith("shop:pay:"):
            if event.callback_query_id:
                await transport.acknowledge(event.callback_query_id)
            try:
                order_id = int(event.callback_data.removeprefix("shop:pay:"))
                await send_order_invoice(
                    session,
                    platform=Platform.BALE,
                    user_id=event.user_id,
                    order_id=order_id,
                    bale_transport=transport,
                )
            except (ValueError, PaymentRejected) as exc:
                await transport.send(event.chat_id, BotReply(str(exc)))
            except BaleApiError:
                raise HTTPException(
                    status_code=502, detail="Bale invoice delivery unavailable"
                ) from None
            return {"status": "invoice_handled"}

        reply = await ShopEngagementFlow(
            display_unit=config.SHOP_DISPLAY_UNIT
        ).reply(event, session)
        if reply is None:
            reply = await ShopOrdersFlow(
                display_unit=config.SHOP_DISPLAY_UNIT
            ).reply(event, session)
        if reply is None:
            reply = await ShopCartFlow(
                display_unit=config.SHOP_DISPLAY_UNIT
            ).reply(event, session)
        if reply is None:
            reply = await CatalogFlow(
                currency_label=config.SHOP_CURRENCY_LABEL,
                display_unit=config.SHOP_DISPLAY_UNIT,
            ).reply(event, session)
    if reply is None:
        return {"status": "ignored"}

    try:
        if event.callback_query_id:
            await transport.acknowledge(event.callback_query_id)
        await transport.send(event.chat_id, reply)
    except BaleApiError:
        # Return an error so the gateway can retry; never log credentials.
        raise HTTPException(status_code=502, detail="Bale delivery failed") from None
    return {"status": "ok"}


@app.post(config.WEBHOOK_PATH)
async def webhook(request: Request):
    """Deduplicate Telegram webhook receipts independently of Bale."""
    if config.TELEGRAM_UPDATE_MODE != "webhook":
        raise HTTPException(status_code=404, detail="Not found")
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    expected = config.WEBHOOK_SECRET_TOKEN or ""
    if not expected or not secret_token or not compare_digest(
        secret_token, expected
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")

    raw = await request.body()
    if len(raw) > 256_000:
        raise HTTPException(status_code=413, detail="Update too large")
    try:
        update_data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON") from None
    if not isinstance(update_data, dict):
        raise HTTPException(status_code=400, detail="Invalid update")
    update_id = update_data.get("update_id")
    if type(update_id) is not int or update_id < 0:
        raise HTTPException(status_code=400, detail="Invalid update ID")

    fresh, receipt_state = await claim_update(
        platform=Platform.TELEGRAM, token=config.TOKEN,
        update_id=update_id,
    )
    if not fresh:
        return {"status": "duplicate", "receipt_state": receipt_state}

    try:
        # Wait until handlers finish before marking the update processed.
        # feed_webhook_update may detach long-running handlers into the
        # background, which would create an inaccurate dedup receipt.
        parsed_update = Update.model_validate(
            update_data, context={"bot": bot}
        )
        await dp.feed_update(bot, parsed_update)
    except Exception:
        await finish_update(
            platform=Platform.TELEGRAM, token=config.TOKEN,
            update_id=update_id, success=False,
        )
        # Do not embed bot tokens, customer content or exception URLs.
        raise HTTPException(
            status_code=502, detail="Telegram webhook processing failed"
        ) from None

    await finish_update(
        platform=Platform.TELEGRAM, token=config.TOKEN,
        update_id=update_id, success=True,
    )
    return {"status": "ok"}


@app.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    traceback_str = traceback.format_exc()
    admin_notification = (
        f"Critical error caused by {exc}\n\n"
        f"Stack trace:\n{traceback_str}"
    )
    if len(admin_notification) > 4096:
        byte_array = bytearray(admin_notification, 'utf-8')
        admin_notification = BufferedInputFile(byte_array, "exception.txt")
    await NotificationService.send_to_admins(admin_notification, None)
    return JSONResponse(
        status_code=500,
        content={"message": f"An error occurred: {str(exc)}"},
    )


def main() -> None:
    uvicorn.run(
        app,
        host=config.WEBAPP_HOST,
        port=config.WEBAPP_PORT,
        proxy_headers=True,
        forwarded_allow_ips="*",
        # Secret URLs must not appear in Uvicorn access logs.
        access_log=not bool(config.BALE_BOT_TOKEN),
    )

