"""Customer Account, addresses, wishlist and preferences on both platforms.

Only an authenticated BotContext and its (bot_id, platform_user_id) may
resolve a StoreCustomer. The chat never receives another Store's address,
phone, wishlist or unsent invoice metadata. Contact verification follows
provider-authenticated Contact.user_id equality, not typed phone input.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_content import Product, ShopIdentity
from models.shop_customer_account_data import (
    ShopCustomerAddress, ShopCustomerPreference, ShopCustomerWishlist,
)
from models.shop_customer_navigation import ShopCustomerChatState
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_bot_catalog_acl import allowed_for_bot, permitted_product_clause, resolve_scope
from services.shop_bot_context import BotContext

_CALLBACK_WISHLIST = re.compile(r"ux:wish:toggle:([1-9][0-9]{0,18})\Z")
_CALLBACK_ADDRESS_CHOOSE = re.compile(r"ux:address:choose:([1-9][0-9]{0,18})\Z")
_CALLBACK_ADDRESS_DELETE = re.compile(r"ux:address:delete:([1-9][0-9]{0,18})\Z")
_CALLBACK_ADDRESS_REMOVE = re.compile(r"ux:address:remove:([1-9][0-9]{0,18})\Z")
_PHONE = re.compile(r"^\+?[0-9]{7,16}\Z")
_ADDRESS_TTL = timedelta(minutes=15)


def verified_contact(event: InboundEvent) -> str:
    """Trust a native contact only when it belongs to the sender."""
    if (
        type(event.contact_user_id) is not int
        or event.contact_user_id != event.user_id
        or not isinstance(event.contact_phone, str)
    ):
        raise ValueError("Only the sender's verified Contact is allowed.")
    normalized = re.sub(r"[ \-()]", "", event.contact_phone)
    if not _PHONE.fullmatch(normalized):
        raise ValueError("Contact phone number is invalid.")
    return normalized


def validate_address(raw: str) -> dict[str, str]:
    """Parse a single bounded, human-readable chat address submission.

    Format: label|recipient|phone|province|city|full address|postal code.
    This is a chat fallback; authenticated Mini Apps may use validated fields.
    """
    if not isinstance(raw, str) or len(raw) > 950:
        raise ValueError("Invalid address input length.")
    fields = [part.strip() for part in raw.split("|")]
    if len(fields) != 7:
        raise ValueError("Address needs all seven labeled fields.")
    label, recipient, phone, province, city, full_address, postal_code = fields
    if not (
        1 <= len(label) <= 40
        and 2 <= len(recipient) <= 100
        and 2 <= len(province) <= 80
        and 2 <= len(city) <= 80
        and 10 <= len(full_address) <= 500
        and 0 <= len(postal_code) <= 20
        and _PHONE.fullmatch(re.sub(r"[ \-()]", "", phone))
        and all(
            char.isprintable()
            for char in label + recipient + province + city + full_address + postal_code
        )
    ):
        raise ValueError("Invalid address field.")
    return {
        "label": label, "recipient": recipient,
        "phone": re.sub(r"[ \-()]", "", phone),
        "province": province, "city": city,
        "full_address": full_address,
        "postal_code": postal_code,
    }


def _actions(*items: tuple[str, str]) -> tuple[tuple[InlineAction, ...], ...]:
    """Produce a consistent one-button-per-row navigational keyboard."""
    return tuple(
        (InlineAction(label, callback),) for label, callback in items
    )


async def customer_for_bot(
    db: AsyncSession, context: BotContext, *, platform_user_id: int,
) -> tuple[ShopIdentity, ShopStoreCustomer]:
    """Resolve the exact verified identity and its owning StoreCustomer."""
    if type(platform_user_id) is not int or platform_user_id <= 0:
        raise ValueError("Invalid customer identity.")
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == context.bot_id,
        ShopIdentity.platform == context.platform.value,
        ShopIdentity.platform_user_id == platform_user_id,
        ShopIdentity.store_id == context.store_id,
    ))
    if identity is None or identity.customer_id is None or identity.is_blocked:
        raise ValueError("Customer account unavailable; please send /start.")
    customer = await db.get(ShopStoreCustomer, identity.customer_id)
    if customer is None or customer.store_id != context.store_id:
        raise ValueError("Customer Store ownership mismatch.")
    return identity, customer


async def _address_entry(
    db: AsyncSession, context: BotContext, customer_id: int, address_id: int,
) -> ShopCustomerAddress | None:
    """Find an address with both Store and Customer ownership verified."""
    return await db.scalar(select(ShopCustomerAddress).where(
        ShopCustomerAddress.id == address_id,
        ShopCustomerAddress.store_id == context.store_id,
        ShopCustomerAddress.customer_id == customer_id,
    ))


class CustomerAccountFlow:
    """Bot-neutral account menus, verified contact, address and wishlist CRUD."""

    def __init__(self, *, bot_context: BotContext) -> None:
        """Bind the immutable Store/Bot identity supplied by the dispatcher."""
        self.context = bot_context

    async def reply(
        self, event: InboundEvent, db: AsyncSession,
    ) -> BotReply | None:
        """Handle only known account actions and expected account form input."""
        action = event.callback_data or ""
        text = (event.text or "").strip()
        if self.context.platform != event.platform:
            raise ValueError("Account BotContext provider mismatch.")

        known = (
            action.startswith(("ux:account", "ux:profile", "ux:address",
                               "ux:addresses", "ux:wish", "ux:links",
                               "ux:notifications", "ux:notify",
                               "ux:language", "ux:privacy"))
            or action in {"ux:wallet", "ux:referral", "ux:phone", "ux:stock:list"}
            or action.startswith("ux:stock:toggle:")
            or text in {"/account", "👤 حساب من", "/address", "/wishlist", "/profile"}
            or event.contact_phone is not None
        )
        state = None
        if not known and text and not text.startswith("/"):
            state = await db.get(
                ShopCustomerChatState,
                (self.context.bot_id, event.user_id),
            )
            if state is None or state.action != "address_input":
                return None
        if not known and state is None:
            return None

        try:
            identity, customer = await customer_for_bot(
                db, self.context, platform_user_id=event.user_id,
            )
        except ValueError:
            return BotReply(
                "ابتدا /start را در همین بات ارسال کنید.",
                _actions(("🏠 منوی اصلی", "shop:home")),
            )

        if event.contact_phone is not None:
            # Unsolicited Contact cards must not change account data.
            # Only the verified owner who clicked the current phone action
            # may complete verification within its short-lived Bot FSM.
            state = await db.get(
                ShopCustomerChatState,
                (self.context.bot_id, event.user_id),
            )
            expiry = state.expires_at if state is not None else None
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if (
                state is None or state.store_id != self.context.store_id
                or state.action != "phone_verification"
                or expiry is None or expiry <= datetime.now(timezone.utc)
            ):
                return BotReply(
                    "برای تأیید شماره، ابتدا از «مشخصات من» "
                    "دکمهٔ تأیید شماره تماس را انتخاب کنید.",
                    _actions(("🪪 مشخصات من", "ux:profile")),
                )
            try:
                phone = verified_contact(event)
            except ValueError:
                return BotReply(
                    "برای تأیید شماره، Contact مربوط به حساب خودتان را ارسال کنید.",
                    _actions(("👤 حساب من", "ux:account")),
                )
            customer.phone = phone
            customer.phone_verified_at = datetime.now(timezone.utc)
            state.action = "idle"
            state.context_ref = None
            await db.commit()
            return BotReply(
                "✅ شمارهٔ تماس متعلق به حساب پیام‌رسان شما تأیید و ثبت شد.",
                _actions(("🪪 پروفایل", "ux:profile")),
            )

        if state is not None and state.action == "address_input":
            expire = state.expires_at
            if expire.tzinfo is None:
                expire = expire.replace(tzinfo=timezone.utc)
            if expire < datetime.now(timezone.utc):
                state.action = "idle"
                await db.commit()
                return BotReply("زمان ثبت آدرس پایان یافت؛ دوباره تلاش کنید.")
            try:
                values = validate_address(text)
            except ValueError:
                return BotReply(
                    "نشانی معتبر نیست. هفت بخش را با | جدا کنید:\n"
                    "عنوان|گیرنده|تلفن|استان|شهر|آدرس کامل|کدپستی",
                    _actions(("لغو", "ux:addresses")),
                )
            exists = await db.scalar(select(ShopCustomerAddress.id).where(
                ShopCustomerAddress.store_id == self.context.store_id,
                ShopCustomerAddress.customer_id == customer.id,
                ShopCustomerAddress.label == values["label"],
            ))
            if exists is not None:
                return BotReply("این عنوان آدرس قبلاً ثبت شده است؛ عنوان دیگری انتخاب کنید.")
            count = int(await db.scalar(select(func.count()).select_from(
                ShopCustomerAddress,
            ).where(
                ShopCustomerAddress.store_id == self.context.store_id,
                ShopCustomerAddress.customer_id == customer.id,
            )) or 0)
            if count >= 10:
                return BotReply("حداکثر ۱۰ نشانی قابل ذخیره است.")
            row = ShopCustomerAddress(
                store_id=self.context.store_id, customer_id=customer.id,
                is_default=count == 0, **values,
            )
            db.add(row)
            state.action = "idle"
            await db.commit()
            return BotReply(
                "✅ نشانی ذخیره شد.",
                _actions(
                    ("📍 نشانی‌های من", "ux:addresses"),
                    ("🛒 سبد خرید", "shop:cart"),
                ),
            )

        if action == "ux:account" or text in {"/account", "👤 حساب من"}:
            return BotReply(
                f"👤 حساب من\n{customer.display_name or identity.first_name or 'مشتری گرامی'}\n"
                "اطلاعات و درخواست‌های شما در همین فروشگاه نگهداری می‌شود.",
                _actions(
                    ("🪪 مشخصات من", "ux:profile"),
                    ("📍 نشانی‌های من", "ux:addresses"),
                    ("💳 اعتبار داخلی", "ux:wallet"),
                    ("♡ علاقه‌مندی‌ها", "ux:wishlist"),
                    ("🔗 حساب‌های متصل", "ux:links"),
                    ("🎁 معرفی دوستان", "ux:referral"),
                    ("🔔 اطلاعیه‌ها", "ux:notifications"),
                    ("📦 اعلان موجودی", "ux:stock:list"),
                    ("🌐 زبان", "ux:language"),
                    ("🔒 حریم خصوصی", "ux:privacy"),
                    ("🏠 منوی اصلی", "shop:home"),
                ),
            )

        if action == "ux:profile" or text == "/profile":
            phone_label = (
                customer.phone if customer.phone and customer.phone_verified_at
                else "تأیید نشده"
            )
            return BotReply(
                "🪪 مشخصات من\n"
                f"نام: {customer.display_name or identity.first_name or 'ثبت نشده'}\n"
                f"شماره تماس: {phone_label}\n"
                "شماره باید توسط Contact متعلق به خودتان تأیید شود.",
                _actions(
                    ("📱 تأیید شماره تماس", "ux:phone"),
                    ("📍 نشانی‌های من", "ux:addresses"),
                    ("👤 حساب من", "ux:account"),
                ),
            )
        if action == "ux:phone":
            state = await db.get(
                ShopCustomerChatState,
                (self.context.bot_id, event.user_id),
            )
            if state is None:
                state = ShopCustomerChatState(
                    bot_id=self.context.bot_id,
                    platform_user_id=event.user_id,
                    store_id=self.context.store_id,
                    expires_at=datetime.now(timezone.utc) + _ADDRESS_TTL,
                )
                db.add(state)
            if state.store_id != self.context.store_id:
                raise ValueError("Contact verification Store mismatch.")
            state.action = "phone_verification"
            state.context_ref = None
            state.expires_at = datetime.now(timezone.utc) + _ADDRESS_TTL
            await db.commit()
            return BotReply(
                "برای تأیید مالکیت شماره، از دکمهٔ رسمی اشتراک شمارهٔ تماس "
                "در پیام‌رسان استفاده کنید. ارسال شماره به صورت متن تأیید محسوب نمی‌شود.",
                request_contact=True,
            )

        if action == "ux:addresses" or text == "/address":
            # Leaving an address-input form also clears its pending state.
            if state is None:
                state = await db.get(
                    ShopCustomerChatState, (self.context.bot_id, event.user_id),
                )
            if state is not None and state.action == "address_input":
                state.action = "idle"
                await db.commit()
            rows = (await db.scalars(select(ShopCustomerAddress).where(
                ShopCustomerAddress.store_id == self.context.store_id,
                ShopCustomerAddress.customer_id == customer.id,
            ).order_by(
                ShopCustomerAddress.is_default.desc(),
                ShopCustomerAddress.id,
            ).limit(10))).all()
            lines = ["📍 نشانی‌های من"]
            buttons = []
            for row in rows:
                lines.append(
                    f"#{row.id} — {row.label} — {row.city}"
                    + (" (پیش‌فرض)" if row.is_default else "")
                )
                buttons.append((
                    InlineAction(
                        f"انتخاب {row.label[:18]}",
                        f"ux:address:choose:{row.id}",
                    ),
                    InlineAction(
                        "🗑 حذف",
                        f"ux:address:delete:{row.id}",
                    ),
                ))
            buttons.extend(_actions(
                ("➕ نشانی جدید", "ux:address:new"),
                ("👤 حساب من", "ux:account"),
            ))
            return BotReply(
                "\n".join(lines) if rows else "هنوز نشانی ثبت نکرده‌اید.",
                tuple(buttons),
            )

        if action == "ux:address:new":
            # Use the module-level model: importing inside this method would
            # make all earlier ShopCustomerChatState reads unbound locals.
            state = await db.get(
                ShopCustomerChatState, (self.context.bot_id, event.user_id),
            )
            if state is None:
                state = ShopCustomerChatState(
                    bot_id=self.context.bot_id,
                    platform_user_id=event.user_id,
                    store_id=self.context.store_id,
                    expires_at=datetime.now(timezone.utc) + _ADDRESS_TTL,
                )
                db.add(state)
            if state.store_id != self.context.store_id:
                raise ValueError("Invalid Store chat ownership.")
            state.action = "address_input"
            state.expires_at = datetime.now(timezone.utc) + _ADDRESS_TTL
            await db.commit()
            return BotReply(
                "📍 آدرس جدید\n"
                "لطفاً هفت بخش را در یک پیام با علامت | جدا کنید:\n"
                "عنوان|نام گیرنده|شماره تماس|استان|شهر|نشانی کامل|کد پستی\n"
                "نمونه:\nخانه|مشتری نمونه|09123456789|تهران|تهران|"
                "خیابان نمونه پلاک ۱|1234567890",
                _actions(("لغو", "ux:addresses")),
            )

        match = _CALLBACK_ADDRESS_CHOOSE.fullmatch(action)
        if match:
            address = await _address_entry(
                db, self.context, customer.id, int(match.group(1)),
            )
            if address is None:
                return BotReply("نشانی پیدا نشد یا متعلق به شما نیست.")
            from services.shop_cart import ShopCartFlow

            cart = await ShopCartFlow(
                bot_context=self.context,
            )._get_cart(event, db, create=True, lock=True)
            if cart is None:
                return BotReply("سبد خرید در دسترس نیست.")
            cart.shipping_address = (
                f"{address.province}، {address.city}، {address.full_address}، "
                f"گیرنده: {address.recipient}، تماس: {address.phone}"
            )[:500]
            cart.revision += 1
            await db.commit()
            return BotReply(
                "✅ نشانی انتخاب شد و به سبد خرید اضافه گردید.",
                _actions(("🛒 سبد خرید", "shop:cart")),
            )

        match = _CALLBACK_ADDRESS_DELETE.fullmatch(action)
        if match:
            address = await _address_entry(
                db, self.context, customer.id, int(match.group(1)),
            )
            if address is None:
                return BotReply("نشانی متعلق به شما پیدا نشد.")
            return BotReply(
                f"حذف نشانی «{address.label}» را تأیید می‌کنید؟ "
                "سوابق سفارش‌های ثبت‌شده تغییر نمی‌کنند.",
                _actions(
                    ("✅ حذف نشانی", f"ux:address:remove:{address.id}"),
                    ("انصراف", "ux:addresses"),
                ),
            )
        match = _CALLBACK_ADDRESS_REMOVE.fullmatch(action)
        if match:
            address = await _address_entry(
                db, self.context, customer.id, int(match.group(1)),
            )
            if address is None:
                return BotReply("نشانی پیدا نشد.")
            was_default = address.is_default
            await db.delete(address)
            await db.flush()
            if was_default:
                remaining = await db.scalar(select(ShopCustomerAddress).where(
                    ShopCustomerAddress.store_id == self.context.store_id,
                    ShopCustomerAddress.customer_id == customer.id,
                ).order_by(ShopCustomerAddress.id).limit(1))
                if remaining is not None:
                    remaining.is_default = True
            await db.commit()
            return BotReply(
                "✅ نشانی حذف شد.",
                _actions(("📍 نشانی‌های من", "ux:addresses")),
            )

        match = _CALLBACK_WISHLIST.fullmatch(action)
        if match:
            product_id = int(match.group(1))
            if not await allowed_for_bot(db, self.context.bot_id, [product_id]):
                return BotReply("این کالا در بات فعلی در دسترس نیست.")
            product = await db.get(Product, product_id)
            if product is None or product.store_id != self.context.store_id:
                return BotReply("کالا متعلق به این فروشگاه نیست.")
            key = (self.context.store_id, customer.id, product_id)
            row = await db.get(ShopCustomerWishlist, key)
            if row is None:
                db.add(ShopCustomerWishlist(
                    store_id=self.context.store_id,
                    customer_id=customer.id, product_id=product_id,
                ))
                response = "♡ محصول به علاقه‌مندی‌ها اضافه شد."
            else:
                await db.delete(row)
                response = "محصول از علاقه‌مندی‌ها حذف شد."
            await db.commit()
            return BotReply(
                response,
                _actions(
                    ("♡ علاقه‌مندی‌ها", "ux:wishlist"),
                    ("📦 مشاهدهٔ محصول", f"shop:item:{product_id}"),
                ),
            )

        if action == "ux:wishlist" or text == "/wishlist":
            scope = await resolve_scope(db, bot_id=self.context.bot_id)
            rows = (await db.execute(select(Product).join(
                ShopCustomerWishlist,
                ShopCustomerWishlist.product_id == Product.id,
            ).where(
                ShopCustomerWishlist.store_id == self.context.store_id,
                ShopCustomerWishlist.customer_id == customer.id,
                permitted_product_clause(scope),
            ).order_by(Product.id.desc()).limit(20))).scalars().all()
            if not rows:
                return BotReply(
                    "♡ هنوز محصول قابل‌نمایشی در علاقه‌مندی‌ها ندارید.",
                    _actions(
                        ("🛍 محصولات", "shop:categories"),
                        ("👤 حساب من", "ux:account"),
                    ),
                )
            buttons = _actions(*(
                (item.name[:60], f"shop:item:{item.id}")
                for item in rows
            ))
            return BotReply(
                f"♡ علاقه‌مندی‌ها — {len(rows)} محصول قابل‌مشاهده",
                buttons + _actions(("👤 حساب من", "ux:account")),
            )

        if action == "ux:links":
            linked = (await db.scalars(select(ShopIdentity).where(
                ShopIdentity.store_id == self.context.store_id,
                ShopIdentity.customer_id == customer.id,
            ).order_by(ShopIdentity.id))).all()
            lines = ["🔗 حساب‌های تأییدشدهٔ این فروشگاه"]
            for item in linked:
                lines.append(f"• {item.platform} — Bot {item.bot_id[:8]}")
            return BotReply(
                "\n".join(lines),
                _actions(
                    ("➕ اتصال حساب دیگر", "ux:links:start"),
                    ("👤 حساب من", "ux:account"),
                ),
            )
        if action == "ux:links:start":
            from services.shop_engagement_flow import ShopEngagementFlow

            return await ShopEngagementFlow(
                bot_context=self.context,
            ).reply(InboundEvent(
                platform=event.platform, chat_id=event.chat_id,
                user_id=event.user_id, text="/linkstart",
            ), db)

        if action == "ux:stock:list":
            from services.shop_customer_notifications import list_stock_alerts

            return await list_stock_alerts(
                db, context=self.context, user_id=event.user_id,
            )
        if action.startswith("ux:stock:toggle:"):
            from services.shop_customer_notifications import toggle_stock_alert

            try:
                product_id = int(action.removeprefix("ux:stock:toggle:"))
            except ValueError:
                return BotReply("شناسه کالا معتبر نیست.")
            if product_id <= 0:
                return BotReply("شناسه کالا معتبر نیست.")
            return await toggle_stock_alert(
                db, context=self.context, user_id=event.user_id,
                product_id=product_id,
            )

        if action in {"ux:wallet", "ux:referral"}:
            from services.shop_engagement_flow import ShopEngagementFlow

            return await ShopEngagementFlow(
                bot_context=self.context,
            ).reply(InboundEvent(
                platform=event.platform, chat_id=event.chat_id,
                user_id=event.user_id,
                text="/wallet" if action == "ux:wallet" else "/referral",
            ), db)

        if action in {"ux:notifications", "ux:notify:on", "ux:notify:off"}:
            if action != "ux:notifications":
                from services.shop_engagement_flow import ShopEngagementFlow

                return await ShopEngagementFlow(
                    bot_context=self.context,
                ).reply(InboundEvent(
                    platform=event.platform, chat_id=event.chat_id,
                    user_id=event.user_id,
                    text=(
                        "/subscribe" if action.endswith(":on") else "/unsubscribe"
                    ),
                ), db)
            return BotReply(
                "🔔 اطلاعیه‌های این بات\n"
                "پیام‌های عملیاتی سفارش از تبلیغات جدا هستند.\n"
                f"تبلیغات: {'فعال' if identity.allow_announcements else 'غیرفعال'}",
                _actions(
                    ("✅ فعال‌سازی تبلیغات", "ux:notify:on"),
                    ("🔕 لغو تبلیغات", "ux:notify:off"),
                    ("👤 حساب من", "ux:account"),
                ),
            )

        if action == "ux:language":
            return BotReply(
                "🌐 زبان فعلی: فارسی. ترجمهٔ کامل زبان‌های دیگر هنوز فعال نیست.",
                _actions(("👤 حساب من", "ux:account")),
            )
        if action == "ux:privacy":
            return BotReply(
                "🔒 حریم خصوصی\nاطلاعات مشتری فقط در همان Store استفاده "
                "می‌شود. اتصال هویت‌ها نیازمند تأیید مالکیت است. برای "
                "دسترسی، اصلاح یا بررسی حذف داده‌ها با پشتیبانی تماس بگیرید.",
                _actions(
                    ("🆘 پشتیبانی", "ux:support"),
                    ("👤 حساب من", "ux:account"),
                ),
            )
        return None
