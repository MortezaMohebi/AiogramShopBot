"""Shared customer wallet, referral and announcement-consent menu.

All store content is in database models; the small set of navigation actions
is intentionally static. Every action works identically on Telegram and Bale.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_content import ShopIdentity, ShopOrder
from models.shop_customer_crm import ShopCustomerConsentEvent
from models.shop_engagement import ShopReferralPolicy, ShopWalletEntry
from services.shop_money import format_rials
from services.shop_referrals import ReferralRejected, ShopReferralService
from services.shop_wallet import ShopWalletService, StoreCreditRejected
from services.shop_bot_context import BotContext
from services.shop_channel_features import get_features
from services.shop_identity_links import LinkRejected, begin, claim, approve, cancel


_CREDIT_PREVIEW = re.compile(r"shop:creditpay:([1-9][0-9]{0,18})\Z")
_CREDIT_CONFIRM = re.compile(r"shop:creditconfirm:([1-9][0-9]{0,18})\Z")


def _home_button() -> tuple[InlineAction, ...]:
    """Reuse the fixed catalogue menu without a dynamic menu builder."""
    return (InlineAction("🏠 صفحه اول", "shop:home"),)


class ShopEngagementFlow:
    """Customer-facing promotional credit, referrals and marketing consent."""

    def __init__(
        self, display_unit: str = "IRR",
        *, bot_context: BotContext | None = None,
    ) -> None:
        """Bind wallet, referral and consent to the authenticated bot."""
        self.display_unit = display_unit
        self.bot_context = bot_context

    def _bot_id(self, platform) -> str:
        """Get the verified bot's immutable identity."""
        if self.bot_context is None:
            raise ValueError("An authenticated bot context is required.")
        if self.bot_context.platform != platform:
            raise StoreCreditRejected("هویت پیام‌رسان معتبر نیست.")
        return self.bot_context.bot_id

    async def reply(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply | None:
        """Resolve only commands owned by the shared engagement service."""
        callback = event.callback_data or ""
        text = (event.text or "").strip()
        command, _, argument = text.partition(" ")

        # Linking requires actions by both provider-authenticated identities
        # and a final confirmation from the initiating account.
        if command == "/linkstart":
            try:
                key = await begin(
                    session, platform=event.platform.value,
                    user_id=event.user_id,
                    bot_id=self._bot_id(event.platform),
                )
                other = "بله" if event.platform.value == "telegram" else "تلگرام"
                return BotReply(
                    "کد محرمانهٔ اتصال حساب‌ها (۱۰ دقیقه):\n"
                    f"{key}\n"
                    f"این کد را در بات {other} با فرمان زیر وارد کنید:\n"
                    f"/linkconfirm {key}\n"
                    "سپس به همین بات برگردید و وارد کنید:\n"
                    f"/linkapprove {key}\n"
                    "کد را به فرد دیگری ندهید.",
                )
            except LinkRejected as error:
                return BotReply(str(error))
        if command in {"/linkconfirm", "/linkapprove", "/linkcancel"}:
            try:
                if command == "/linkconfirm":
                    await claim(
                        session, platform=event.platform.value,
                        user_id=event.user_id, token=argument.strip(),
                        bot_id=self._bot_id(event.platform),
                    )
                    return BotReply(
                        "حساب دوم تأیید اولیه شد. صاحب حساب اول باید در "
                        "پیام‌رسان اول، فرمان /linkapprove را با همان کد ارسال کند.",
                    )
                if command == "/linkapprove":
                    await approve(
                        session, platform=event.platform.value,
                        user_id=event.user_id, token=argument.strip(),
                        bot_id=self._bot_id(event.platform),
                    )
                    return BotReply(
                        "✅ هویت‌های تأییدشده در یک پروندهٔ مشتری ثبت شدند. "
                        "اشتراک سبد و اعتبار تابع سیاست فروشگاه است؛ "
                        "هیچ مانده‌ای خودکار منتقل نشده است.",
                    )
                await cancel(
                    session, platform=event.platform.value,
                    user_id=event.user_id, token=argument.strip(),
                        bot_id=self._bot_id(event.platform),
                )
                return BotReply("درخواست اتصال لغو شد.")
            except LinkRejected as error:
                return BotReply(str(error))
        if (
            callback in {"shop:wallet"} or text in ("/wallet", "💳 اعتبار من")
            or _CREDIT_PREVIEW.fullmatch(callback)
            or _CREDIT_CONFIRM.fullmatch(callback)
        ):
            features = await get_features(
                session, event.platform.value,
                bot_id=self._bot_id(event.platform),
            )
            if not features.store_credit_enabled:
                return BotReply(
                    "اعتبار داخلی فروشگاه برای این پیام‌رسان غیرفعال شده است.",
                    (_home_button(),),
                )

        match = _CREDIT_PREVIEW.fullmatch(callback)
        if match:
            return await self._credit_preview(
                event, session, int(match.group(1))
            )
        match = _CREDIT_CONFIRM.fullmatch(callback)
        if match:
            return await self._credit_confirm(
                event, session, int(match.group(1))
            )

        if callback == "shop:wallet" or text in (
            "/wallet", "💳 اعتبار من"
        ):
            return await self._wallet(event, session)
        if callback == "shop:referral" or text in (
            "/referral", "🎁 معرفی دوستان"
        ):
            return await self._referral(event, session)
        if callback in ("shop:subscribe", "shop:unsubscribe") or text in (
            "/subscribe", "/unsubscribe",
            "📣 دریافت اطلاعیه", "🔕 لغو اطلاعیه",
        ):
            enable = callback == "shop:subscribe" or text in (
                "/subscribe", "📣 دریافت اطلاعیه"
            )
            return await self._consent(event, session, enable=enable)

        if text.startswith("/ref ") or text.startswith("/start R-"):
            code = text.split(" ", 1)[1].strip()
            try:
                result = await ShopReferralService.claim(
                    session,
                    platform=event.platform,
                    user_id=event.user_id,
                    code=code,
                    bot_id=self._bot_id(event.platform),
                )
            except ReferralRejected as error:
                result = str(error)
            return BotReply(result, (_home_button(),))
        return None

    async def _wallet(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Show actual store credit and its last five ledger operations."""
        identity = await ShopWalletService.find_identity(
            session, event.platform, event.user_id,
            bot_id=self._bot_id(event.platform),
        )
        balance = await ShopWalletService.balance(
            session, event.platform, event.user_id,
            bot_id=self._bot_id(event.platform),
        )
        entries = []
        if identity is not None:
            from models.shop_engagement import ShopWalletAccount

            from services.shop_store_commerce import policy_for

            policy = await policy_for(
                session, store_id=identity.store_id,
            )
            if policy.credit_scope == "customer" and identity.customer_id:
                criteria = (
                    ShopWalletAccount.store_id == identity.store_id,
                    ShopWalletAccount.customer_id == identity.customer_id,
                    ShopWalletAccount.scope == "customer",
                )
            else:
                criteria = (
                    ShopWalletAccount.identity_id == identity.id,
                    ShopWalletAccount.scope == "identity",
                )
            account_id = await session.scalar(
                select(ShopWalletAccount.id).where(*criteria)
            )
            if account_id is not None:
                results = await session.execute(
                    select(ShopWalletEntry)
                    .where(ShopWalletEntry.account_id == account_id)
                    .order_by(ShopWalletEntry.id.desc())
                    .limit(5)
                )
                entries = results.scalars().all()
        history = "\n".join(
            f"{'+' if entry.delta_irr > 0 else '−'}"
            f"{format_rials(abs(entry.delta_irr), self.display_unit)}"
            f" — {entry.reason[:60]}"
            for entry in entries
        )
        features = await get_features(
                session, event.platform.value,
                bot_id=self._bot_id(event.platform),
            )
        return BotReply(
            f"💳 {features.store_credit_label}\n"
            f"موجودی: {format_rials(balance, self.display_unit)}\n\n"
            "این اعتبار جدا از کیف پول شخصی بله و رمزارز تلگرام است.\n"
            + (history or "هنوز تراکنشی ثبت نشده است."),
            (_home_button(),),
        )

    async def _referral(
        self, event: InboundEvent, session: AsyncSession
    ) -> BotReply:
        """Show an optional code only when merchant referral policy is active."""
        policy = await session.get(ShopReferralPolicy, 1)
        if policy is None or not policy.is_enabled or policy.percent <= 0:
            return BotReply(
                "برنامه معرفی مشتری در حال حاضر فعال نیست.",
                (_home_button(),),
            )
        try:
            code = await ShopReferralService.code(
                session, event.platform, event.user_id,
                bot_id=self._bot_id(event.platform),
            )
        except ReferralRejected as error:
            return BotReply(str(error))
        return BotReply(
            "🎁 معرفی دوستان\n"
            f"کد شما: {code}\n"
            "دوست شما قبل از اولین خرید، این کد را با دستور "
            f"/ref {code} در همین پیام‌رسان ثبت کند.\n"
            "پاداش تنها بعد از پرداخت معتبر و مطابق سیاست فروشگاه "
            "به اعتبار داخلی معرف افزوده می‌شود.",
            (_home_button(),),
        )

    async def _consent(
        self, event: InboundEvent, session: AsyncSession, *, enable: bool
    ) -> BotReply:
        """Respect explicit customer choice, defaulting to no announcements."""
        identity = await ShopWalletService.find_identity(
            session, event.platform, event.user_id,
            bot_id=self._bot_id(event.platform),
        )
        if identity is None:
            return BotReply("ابتدا /start را ارسال کنید.")
        # Consent changes are initiated by the authenticated Bot API user,
        # never set by a manager or inferred from a broadcast delivery.
        identity.allow_announcements = enable
        session.add(ShopCustomerConsentEvent(
            identity_id=identity.id,
            allowed=enable,
            source=f"{event.platform.value}_command",
            topic="shop_announcements",
        ))
        await session.commit()
        return BotReply(
            "✅ دریافت اطلاعیه‌های فروشگاه فعال شد."
            if enable else "✅ دریافت اطلاعیه‌های تبلیغاتی متوقف شد.",
            ((_home_button()),),
        )

    async def _credit_preview(
        self, event: InboundEvent, session: AsyncSession, order_id: int
    ) -> BotReply:
        """Ask for a second explicit confirmation before any wallet debit."""
        order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.id == order_id,
                ShopOrder.bot_id == self._bot_id(event.platform),
                ShopOrder.platform == event.platform.value,
                ShopOrder.platform_user_id == event.user_id,
            )
        )
        if order is None:
            return BotReply("سفارش متعلق به این حساب نیست.")
        if order.status != "approved_unpaid" or order.provider != "manual_review":
            return BotReply("این سفارش آماده پرداخت با اعتبار نیست.")
        balance = await ShopWalletService.balance(
            session, event.platform, event.user_id,
            bot_id=self._bot_id(event.platform),
        )
        if balance < order.total_irr:
            return BotReply(
                "موجودی اعتبار کافی نیست.\n"
                f"موجودی: {format_rials(balance, self.display_unit)}\n"
                f"مبلغ سفارش: {format_rials(order.total_irr, self.display_unit)}",
                ((InlineAction("📦 سفارش‌های من", "shop:orders"),),),
            )
        return BotReply(
            f"پرداخت سفارش #{order.id} از اعتبار فروشگاه؟\n"
            f"مبلغ: {format_rials(order.total_irr, self.display_unit)}\n"
            "با تأیید، این مبلغ از موجودی اعتبار شما کسر می‌شود.",
            ((
                InlineAction("✅ تأیید پرداخت", f"shop:creditconfirm:{order.id}"),
                InlineAction("انصراف", "shop:orders"),
            ),),
        )

    async def _credit_confirm(
        self, event: InboundEvent, session: AsyncSession, order_id: int
    ) -> BotReply:
        """Deduct merchant credit atomically with purchased item inventory."""
        try:
            order, changed = await ShopWalletService.pay_order(
                session,
                platform=event.platform,
                user_id=event.user_id,
                order_id=order_id,
                bot_id=self._bot_id(event.platform),
            )
        except StoreCreditRejected as error:
            return BotReply(str(error), ((_home_button()),))
        return BotReply(
            (
                f"✅ سفارش #{order.id} با اعتبار داخلی پرداخت شد."
                if changed
                else f"سفارش #{order.id} قبلاً با اعتبار داخلی پرداخت شده است."
            ),
            ((InlineAction("📦 سفارش‌های من", "shop:orders"),),),
        )
