"""Audited, idempotent integer-IRR store credit independent of Bale Wallet.

The shop's promotional credit is *not* the user's Bale account balance and
cannot be withdrawn as cryptocurrency. Every credit/debit is an append-only
ledger entry; balance changes are locked and committed as one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from models.shop_checkout import ShopCoupon, ShopOrderLine
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_engagement import ShopWalletAccount, ShopWalletEntry
from models.shop_payment import ShopPaymentAttempt, ShopRefundCase
from services.shop_cart import CartRejected, validate_coupon
from services.shop_channel_features import get_features
from services.shop_payment_rails import rail_enabled
from services.shop_bot_catalog_acl import (
    allowed_for_bot, lock_bot_catalog_policy,
)
from models.shop_scope import legacy_id
from services.shop_money import MAX_RIALS, to_rials


class StoreCreditRejected(ValueError):
    """A financial operation was rejected without altering the ledger."""


class ShopWalletService:
    """Provide shop-owned credit balance, ledger and paid-order operations."""

    @staticmethod
    async def find_identity(
        session: AsyncSession, platform: Platform, user_id: int,
        *, bot_id: str | None = None,
    ) -> ShopIdentity | None:
        """Find the exact messaging identity; never merge numeric IDs."""
        if type(user_id) is not int or user_id <= 0:
            return None
        return await session.scalar(
            select(ShopIdentity).where(
                ShopIdentity.bot_id == (bot_id or legacy_id(platform.value)),
                ShopIdentity.platform == platform.value,
                ShopIdentity.platform_user_id == user_id,
            )
        )

    @staticmethod
    async def _account(
        session: AsyncSession, identity_id: int
    ) -> ShopWalletAccount:
        """Lock an existing wallet or create it under a unique savepoint."""
        identity = await session.get(ShopIdentity, identity_id)
        if identity is None:
            raise StoreCreditRejected("حساب مشتری یافت نشد.")
        stmt = select(ShopWalletAccount).where(
            ShopWalletAccount.identity_id == identity_id
        ).with_for_update()
        account = await session.scalar(stmt)
        if account is not None:
            if account.bot_id is not None and account.bot_id != identity.bot_id:
                raise StoreCreditRejected("مالکیت کیف پول با بات مطابقت ندارد.")
            if account.bot_id is None:
                account.bot_id = identity.bot_id
            return account

        # A nested transaction protects the outer payment transaction from
        # the uniqueness race when two requests first open the same wallet.
        try:
            async with session.begin_nested():
                session.add(
                    ShopWalletAccount(
                        bot_id=identity.bot_id,
                        identity_id=identity_id, balance_irr=0,
                    )
                )
                await session.flush()
        except IntegrityError:
            pass
        account = await session.scalar(stmt)
        if account is None:
            raise StoreCreditRejected("دسترسی به اعتبار فعلاً ممکن نیست.")
        return account

    @staticmethod
    async def balance(
        session: AsyncSession, platform: Platform, user_id: int,
        *, bot_id: str | None = None,
    ) -> int:
        """Return merchant store credit only, not external Bale wallet funds."""
        identity = await ShopWalletService.find_identity(
            session, platform, user_id, bot_id=bot_id,
        )
        if identity is None:
            return 0
        value = await session.scalar(
            select(ShopWalletAccount.balance_irr).where(
                ShopWalletAccount.identity_id == identity.id
            )
        )
        return int(value or 0)

    @staticmethod
    async def apply(
        session: AsyncSession,
        *,
        identity_id: int,
        delta_irr: int,
        operation_key: str,
        reason: str,
        actor: str,
    ) -> tuple[ShopWalletEntry, bool]:
        """Apply a nonzero signed amount once, without committing the caller.

        A globally unique operation_key is required for retries; reusing an
        existing key for a different owner or delta raises a hard error.
        """
        if (
            type(delta_irr) is not int or delta_irr == 0
            or abs(delta_irr) > MAX_RIALS
            or not 8 <= len(operation_key) <= 128
            or not 1 <= len(reason) <= 255
            or not 1 <= len(actor) <= 120
        ):
            raise StoreCreditRejected("مبلغ یا سند عملیات اعتبار معتبر نیست.")

        prior = await session.scalar(
            select(ShopWalletEntry).where(
                ShopWalletEntry.operation_key == operation_key
            )
        )
        if prior is not None:
            account = await session.get(ShopWalletAccount, prior.account_id)
            if (
                account is None or account.identity_id != identity_id
                or prior.delta_irr != delta_irr
            ):
                raise StoreCreditRejected("شناسه عملیات قبلاً برای مبلغ دیگری ثبت شد.")
            return prior, False

        account = await ShopWalletService._account(session, identity_id)
        # Another request may have committed this key while our request
        # waited on the row lock. Avoid a double debit on concurrent retries.
        concurrent = await session.scalar(
            select(ShopWalletEntry).where(
                ShopWalletEntry.operation_key == operation_key
            )
        )
        if concurrent is not None:
            if concurrent.account_id != account.id or concurrent.delta_irr != delta_irr:
                raise StoreCreditRejected("کلید عملیات برای مبلغ دیگری ثبت شده است.")
            return concurrent, False
        balance_after = account.balance_irr + delta_irr
        if not 0 <= balance_after <= MAX_RIALS:
            raise StoreCreditRejected("موجودی اعتبار کافی نیست یا سقف آن پر شده است.")
        account.balance_irr = balance_after
        identity = await session.get(ShopIdentity, identity_id)
        if identity is None or identity.bot_id != account.bot_id:
            raise StoreCreditRejected("مالکیت اعتبار قابل تأیید نیست.")
        entry = ShopWalletEntry(
            bot_id=identity.bot_id,
            account_id=account.id,
            operation_key=operation_key,
            delta_irr=delta_irr,
            balance_after_irr=balance_after,
            reason=reason,
            actor=actor,
        )
        session.add(entry)
        await session.flush()
        return entry, True

    @staticmethod
    async def pay_order(
        session: AsyncSession,
        *,
        platform: Platform,
        user_id: int,
        order_id: int,
        bot_id: str | None = None,
    ) -> tuple[ShopOrder, bool]:
        """Pay an approved shared order fully from shop credit, exactly once.

        No external Bot API or crypto provider is involved. Insufficient
        balance, invalid coupon or unavailable stock leaves the order unpaid.
        """
        result = await session.execute(
            select(ShopOrder).where(
                ShopOrder.id == order_id,
                ShopOrder.bot_id == (bot_id or legacy_id(platform.value)),
                ShopOrder.platform == platform.value,
                ShopOrder.platform_user_id == user_id,
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise StoreCreditRejected("سفارش متعلق به این حساب نیست.")
        if order.provider == "store_credit" and order.status == "paid":
            return order, False
        features = await get_features(session, platform.value)
        if not features.store_credit_enabled:
            raise StoreCreditRejected(
                "پرداخت با اعتبار داخلی برای این پیام‌رسان غیرفعال است."
            )
        if not await rail_enabled(session, platform.value, "store_credit"):
            raise StoreCreditRejected(
                "این روش پرداخت با اعتبار داخلی غیرفعال است."
            )
        if order.provider != "manual_review" or order.status != "approved_unpaid":
            raise StoreCreditRejected("این سفارش آماده پرداخت با اعتبار نیست.")

        identity = await ShopWalletService.find_identity(
            session, platform, user_id, bot_id=bot_id,
        )
        if identity is None:
            raise StoreCreditRejected("ابتدا حساب فروشگاه را فعال کنید.")
        account = await ShopWalletService._account(session, identity.id)
        amount = to_rials(order.total_irr)
        if amount <= 0 or account.balance_irr < amount:
            raise StoreCreditRejected("موجودی اعتبار فروشگاه کافی نیست.")
        if await session.scalar(
            select(ShopPaymentAttempt.id).where(
                ShopPaymentAttempt.order_id == order.id
            )
        ) is not None:
            raise StoreCreditRejected("برای این سفارش قبلاً روش پرداخت انتخاب شده است.")

        result = await session.execute(
            select(ShopOrderLine, Product)
            .join(Product, Product.id == ShopOrderLine.product_id)
            .where(ShopOrderLine.order_id == order.id)
            .order_by(ShopOrderLine.product_id)
            .with_for_update(of=Product)
        )
        pairs = result.all()
        if pairs:
            await lock_bot_catalog_policy(
                session, bot_id or legacy_id(platform.value),
            )
        if not pairs or not await allowed_for_bot(
            session, bot_id or legacy_id(platform.value),
            [product.id for _, product in pairs],
        ):
            raise StoreCreditRejected(
                "یک یا چند کالای سفارش در این بات دیگر قابل خرید نیستند."
            )
        if any(
            not product.is_published
            or product.stock_quantity < line.quantity
            or line.quantity < 1
            or line.total_irr != line.unit_price_irr * line.quantity
            for line, product in pairs
        ):
            raise StoreCreditRejected("موجودی یا مشخصات اقلام معتبر نیست.")
        if (
            sum(line.total_irr for line, _ in pairs)
            != order.subtotal_irr
            or order.subtotal_irr - (order.discount_irr or 0)
            + (order.shipping_irr or 0) != amount
        ):
            raise StoreCreditRejected("مبلغ سفارش با اقلام آن مطابقت ندارد.")

        coupon = None
        if order.coupon_id is not None:
            coupon = await session.scalar(
                select(ShopCoupon)
                .where(ShopCoupon.id == order.coupon_id)
                .with_for_update()
            )
            try:
                if coupon is None or (
                    validate_coupon(coupon, order.subtotal_irr)
                    != order.discount_irr
                ):
                    raise StoreCreditRejected("کد تخفیف این سفارش معتبر نیست.")
            except CartRejected:
                raise StoreCreditRejected("اعتبار کد تخفیف تمام شده است.") from None

        await ShopWalletService.apply(
            session,
            identity_id=identity.id,
            delta_irr=-amount,
            operation_key=f"store-credit-pay-order:{order.id}",
            reason=f"Payment for order #{order.id}",
            actor=f"{bot_id or legacy_id(platform.value)}:{user_id}",
        )
        for line, product in pairs:
            product.stock_quantity -= line.quantity
        if coupon is not None:
            coupon.used_count += 1
        now = datetime.now(timezone.utc)
        session.add(
            ShopPaymentAttempt(
                order_id=order.id,
                bot_id=bot_id or legacy_id(platform.value),
                platform=platform.value,
                provider="store_credit",
                currency="IRR",
                amount=amount,
                payload=order.invoice_payload,
                status="paid",
                completed_at=now,
            )
        )
        order.provider = "store_credit"
        order.status = "paid"
        order.payment_currency = "IRR"
        order.payment_amount = amount
        order.paid_at = now
        await session.commit()
        return order, True

    @staticmethod
    async def refund_order(
        session: AsyncSession,
        *,
        case_id: int,
        actor: str,
    ) -> ShopRefundCase:
        """Return store credit only after explicit finance approval."""
        case = await session.scalar(
            select(ShopRefundCase).where(
                ShopRefundCase.id == case_id
            ).with_for_update()
        )
        if case is None or case.status not in (
            "requested", "provider_pending"
        ):
            raise StoreCreditRejected("پرونده بازپرداخت قابل اقدام نیست.")
        order = await session.scalar(
            select(ShopOrder).where(
                ShopOrder.id == case.order_id
            ).with_for_update()
        )
        attempt = await session.scalar(
            select(ShopPaymentAttempt).where(
                ShopPaymentAttempt.order_id == order.id
            ).with_for_update()
        )
        if (
            order.provider != "store_credit"
            or order.status != "paid"
            or attempt is None or attempt.status != "paid"
        ):
            raise StoreCreditRejected("این پرداخت از اعتبار داخلی نیست.")
        identity = await ShopWalletService.find_identity(
            session,
            Platform(order.platform),
            order.platform_user_id,
            bot_id=order.bot_id,
        )
        if identity is None:
            raise StoreCreditRejected("هویت گیرنده یافت نشد.")
        await ShopWalletService.apply(
            session,
            identity_id=identity.id,
            delta_irr=to_rials(order.total_irr),
            operation_key=f"store-credit-refund-order:{order.id}",
            reason=f"Refund order #{order.id}",
            actor=actor,
        )
        now = datetime.now(timezone.utc)
        case.provider_reference = f"store-credit-refund-order:{order.id}"
        case.resolution_note = f"Approved by {actor}"
        case.resolved_at = now
        case.status = "confirmed"
        attempt.status = "refunded"
        order.status = "refunded"
        # Do not restock potentially shipped products without a return check.
        await session.commit()
        return case
