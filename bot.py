import asyncio
import json
import logging
from contextlib import suppress
import sys
from hmac import compare_digest

from aiohttp import ClientSession, ClientTimeout
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BufferedInputFile
from redis.asyncio import Redis
from sqladmin import Admin

import config
from aiogram import Dispatcher
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.staticfiles import StaticFiles

from admin import authentication_backend
from channels.bale import BaleApiError, BaleTransport
from channels.contracts import BotReply, Platform, normalize_update
from services.shop_channel_catalog import CatalogFlow
from services.bale_wallet import BaleWalletService, CheckoutRejected
from services.shop_identity import is_blocked, register_customer
from dashboard.persian import localize_model_view
from dashboard.media_views import ShopMediaPreviewView, ShopUploadView
from db import create_db_and_tables, engine, get_db_session
import uvicorn
from fastapi.responses import JSONResponse
from enums.cryptocurrency import Cryptocurrency
from models.shop_checkout import (
    ShopCartAdmin, ShopCartItemAdmin, ShopShippingMethodAdmin,
    ShopCouponAdmin, ShopOrderLineAdmin,
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
from utils.utils import validate_i18n

redis = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD)
session = create_telegram_session()
bot = create_bot(config.TOKEN, session)
dp = Dispatcher(storage=RedisStorage(redis))


async def _startup() -> None:
    await create_db_and_tables()
    static = Path("static")
    if static.exists() is False:
        static.mkdir()
    me = await bot.get_me()
    photos = await bot.get_user_profile_photos(me.id)
    # No hardcoded product or placeholder image and no external stock-photo URL.
    # The legacy upstream views require a Telegram file_id for their navigation.
    bot_photo_id = (
        photos.photos[0][-1].file_id
        if photos.total_count > 0
        else config.DEFAULT_MEDIA_FILE_ID
    )
    if not bot_photo_id:
        raise RuntimeError(
            "Configure DEFAULT_MEDIA_FILE_ID for legacy Telegram menus "
            "or set a profile image for the bot before starting."
        )
    with open("static/no_image.jpeg", "w") as f:
        f.write(bot_photo_id)
    await MediaService.update_inaccessible_media(bot)
    validate_i18n()
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
        except Exception as e:
            logging.warning(e)

    if config.TELEGRAM_UPDATE_MODE == "webhook":
        await bot.set_webhook(
            url=config.WEBHOOK_URL,
            secret_token=config.WEBHOOK_SECRET_TOKEN,
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
    else:
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
admin.add_model_view(localize_model_view(UserAdmin))
admin.add_model_view(localize_model_view(BuyAdmin))
admin.add_model_view(localize_model_view(ShippingOptionAdmin))
admin.add_model_view(localize_model_view(CouponAdmin))
admin.add_model_view(localize_model_view(CategoryAdmin))
admin.add_model_view(localize_model_view(SubcategoryAdmin))
admin.add_model_view(localize_model_view(ItemAdmin))
admin.add_model_view(localize_model_view(DepositAdmin))
admin.add_model_view(localize_model_view(BuyItemAdmin))
admin.add_model_view(localize_model_view(PaymentAdmin))
admin.add_model_view(localize_model_view(CartAdmin))
admin.add_model_view(localize_model_view(CartItemAdmin))
admin.add_model_view(localize_model_view(ReferralBonusAdmin))
admin.add_model_view(localize_model_view(ReviewAdmin))
admin.add_model_view(ShopSettingsAdmin)
admin.add_model_view(ShopCategoryAdmin)
admin.add_model_view(ProductAdmin)
admin.add_model_view(ProductMediaAdmin)
admin.add_model_view(TestimonialAdmin)
admin.add_model_view(ShopIdentityAdmin)
admin.add_model_view(ShopOrderAdmin)
admin.add_model_view(ShopShippingMethodAdmin)
admin.add_model_view(ShopCouponAdmin)
admin.add_model_view(ShopCartAdmin)
admin.add_model_view(ShopCartItemAdmin)
admin.add_model_view(ShopOrderLineAdmin)
admin.add_view(ShopUploadView)
admin.add_view(ShopMediaPreviewView)

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
                accepted, reason = await BaleWalletService.validate_pre_checkout(
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
                order, changed = await BaleWalletService.confirm_success(
                    session,
                    transport,
                    payer_id=payer["id"],
                    chat_id=chat["id"],
                    payment=payment_message["successful_payment"],
                )
        except CheckoutRejected:
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
        if event.callback_data and event.callback_data.startswith("shop:checkout:"):
            if not config.BALE_WALLET_CHECKOUT_ENABLED:
                await transport.send(
                    event.chat_id,
                    BotReply("پرداخت کیف پول بله هنوز برای این فروشگاه فعال نیست."),
                )
                return {"status": "disabled"}
            try:
                product_id = int(event.callback_data.rsplit(":", 1)[1])
                if event.callback_query_id:
                    await transport.acknowledge(event.callback_query_id)
                await BaleWalletService.create_invoice(
                    session,
                    transport,
                    product_id=product_id,
                    platform_user_id=event.user_id,
                    chat_id=event.chat_id,
                    provider_token=config.BALE_WALLET_PROVIDER_TOKEN,
                )
            except (ValueError, CheckoutRejected) as exc:
                await transport.send(event.chat_id, BotReply(str(exc)))
            except BaleApiError:
                raise HTTPException(status_code=502, detail="Bale delivery failed") from None
            return {"status": "ok"}

        if (event.text and event.text.strip() in ("/orders", "📦 سفارش‌های من")) or event.callback_data == "shop:orders":
            text = await BaleWalletService.list_orders(
                session, platform="bale", platform_user_id=event.user_id
            )
            reply = BotReply(text)
        else:
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
    if config.TELEGRAM_UPDATE_MODE != "webhook":
        raise HTTPException(status_code=404, detail="Not found")
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret_token != config.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    try:
        update_data = await request.json()
        await dp.feed_webhook_update(bot, update_data)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error processing webhook: {e}")
        return {"status": "error"}, status.HTTP_500_INTERNAL_SERVER_ERROR


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

