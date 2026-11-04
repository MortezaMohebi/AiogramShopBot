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
from services.shop_checkout_policy import legal_credit_for_items
from services.shop_store_commerce import policy_for


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
        session: AsyncSession, identity_id: int,
        *, forced_account_id: int | None = None,
    ) -> ShopWalletAccount:
        """Lock the effective Customer or legacy identity credit account.

        The only way to select a shared wallet is an explicit Store policy
        and a verified customer_id. No native Bale/Telegram provider balance
        participates in this credit account.
        """
        identity = await session.get(ShopIdentity, identity_id)
        if identity is None:
            raise StoreCreditRejected("حساب مشتری یافت نشد.")
        scope = (await policy_for(
            session, store_id=identity.store_id,
        )).credit_scope
        shared = scope == "customer" and identity.customer_id is not None
        if forced_account_id is not None:
            account = await session.scalar(select(ShopWalletAccount).where(
                ShopWalletAccount.id == forced_account_id,
            ).with_for_update())
            if account is None:
                raise StoreCreditRejected("حساب اعتبار تاریخی پیدا نشد.")
            ShopWalletService._check_ownership(account, identity)
            return account

        statement = select(ShopWalletAccount).where(
            ShopWalletAccount.store_id == identity.store_id,
            ShopWalletAccount.scope == (
                "customer" if shared else "identity"
            ),
        )
        if shared:
            statement = statement.where(
                ShopWalletAccount.customer_id == identity.customer_id,
            )
        else:
            statement = statement.where(
                ShopWalletAccount.identity_id == identity.id,
            )
        account = await session.scalar(statement.with_for_update())
        if account is not None:
            ShopWalletService._check_ownership(account, identity)
            return account

        try:
            async with session.begin_nested():
                account = ShopWalletAccount(
                    scope="customer" if shared else "identity",
                    store_id=identity.store_id,
                    customer_id=identity.customer_id,
                    identity_id=None if shared else identity.id,
                    bot_id=None if shared else identity.bot_id,
                    balance_irr=0,
                )
                session.add(account)
                await session.flush()
        except IntegrityError:
            account = await session.scalar(statement.with_for_update())
            if account is None:
                raise StoreCreditRejected("دسترسی به اعتبار ممکن نیست.") from None
        ShopWalletService._check_ownership(account, identity)
        return account

    @staticmethod
    def _check_ownership(
        account: ShopWalletAccount, identity: ShopIdentity,
    ) -> None:
        """Refuse access to accounts outside the verified Store/owner."""
        if account.store_id != identity.store_id or (
            account.scope == "identity" and (
                account.identity_id != identity.id
                or account.bot_id != identity.bot_id
            )
        ) or (
            account.scope == "customer" and (
                account.customer_id is None
                or account.customer_id != identity.customer_id
                or account.identity_id is not None
                or account.bot_id is not None
            )
        ):
            raise StoreCreditRejected("مالکیت اعتبار قابل تأیید نیست.")

    @staticmethod
    async def balance(
        session: AsyncSession, platform: Platform, user_id: int,
        *, bot_id: str | None = None,
    ) -> int:
        """Return only this Store's effective internal merchant credit."""
        identity = await ShopWalletService.find_identity(
            session, platform, user_id, bot_id=bot_id,
        )
        if identity is None:
            return 0
        scope = (await policy_for(
            session, store_id=identity.store_id,
        )).credit_scope
        if scope == "customer" and identity.customer_id is not None:
            criteria = (
                ShopWalletAccount.store_id == identity.store_id,
                ShopWalletAccount.customer_id == identity.customer_id,
                ShopWalletAccount.scope == "customer",
            )
        else:
            criteria = (
                ShopWalletAccount.store_id == identity.store_id,
                ShopWalletAccount.identity_id == identity.id,
                ShopWalletAccount.scope == "identity",
            )
        return int(await session.scalar(select(
            ShopWalletAccount.balance_irr,
        ).where(*criteria)) or 0)

    @staticmethod
    async def apply(
        session: AsyncSession, *, identity_id: int,
        delta_irr: int, operation_key: str, reason: str,
        actor: str, forced_account_id: int | None = None,
    ) -> tuple[ShopWalletEntry, bool]:
        """Record one signed, globally idempotent store-credit mutation."""
        if (
            type(delta_irr) is not int or delta_irr == 0
            or abs(delta_irr) > MAX_RIALS
            or not 8 <= len(operation_key) <= 128
            or not 1 <= len(reason) <= 255
            or not 1 <= len(actor) <= 120
        ):
            raise StoreCreditRejected("مبلغ یا سند عملیات اعتبار معتبر نیست.")

        identity = await session.get(ShopIdentity, identity_id)
        if identity is None:
            raise StoreCreditRejected("حساب مشتری یافت نشد.")
        prior = await session.scalar(select(ShopWalletEntry).where(
            ShopWalletEntry.operation_key == operation_key,
        ))
        if prior is not None:
            account = await session.get(ShopWalletAccount, prior.account_id)
            if (
                account is None
                or (prior.source_identity_id not in (None, identity_id))
                or prior.delta_irr != delta_irr
                or (
                    forced_account_id is not None
                    and prior.account_id != forced_account_id
                )
            ):
                raise StoreCreditRejected("شناسه عملیات برای سند دیگری استفاده شد.")
            ShopWalletService._check_ownership(account, identity)
            return prior, False

        account = await ShopWalletService._account(
            session, identity_id, forced_account_id=forced_account_id,
        )
        concurrent = await session.scalar(select(ShopWalletEntry).where(
            ShopWalletEntry.operation_key == operation_key,
        ))
        if concurrent is not None:
            if (
                concurrent.account_id != account.id
                or concurrent.delta_irr != delta_irr
                or concurrent.source_identity_id not in (None, identity_id)
            ):
                raise StoreCreditRejected("کلید عملیات تکراری با سند دیگری است.")
            return concurrent, False

        balance_after = account.balance_irr + delta_irr
        if not 0 <= balance_after <= MAX_RIALS:
            raise StoreCreditRejected("موجودی اعتبار کافی نیست یا سقف آن پر شده است.")
        account.balance_irr = balance_after
        entry = ShopWalletEntry(
            account_id=account.id,
            source_identity_id=identity.id,
            bot_id=identity.bot_id,
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
        features = await get_features(
            session, platform.value,
            bot_id=bot_id or legacy_id(platform.value),
        )
        if not features.store_credit_enabled:
            raise StoreCreditRejected(
                "پرداخت با اعتبار داخلی برای این پیام‌رسان غیرفعال است."
            )
        if not await rail_enabled(
            session, platform.value, "store_credit",
            bot_id=bot_id or legacy_id(platform.value),
        ):
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
        if not legal_credit_for_items(
            platform, {product.product_type for _, product in pairs},
        ):
            raise StoreCreditRejected(
                "پرداخت کالای دیجیتال تلگرام فقط با Telegram Stars مجاز است."
            )
        if order.terms_accepted_at is None:
            raise StoreCreditRejected(
                "شرایط فروش این سفارش تأیید نشده است."
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
                store_id=order.store_id,
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
        debit = await session.scalar(select(ShopWalletEntry).where(
            ShopWalletEntry.operation_key == f"store-credit-pay-order:{order.id}",
        ))
        if debit is None or debit.delta_irr != -to_rials(order.total_irr):
            raise StoreCreditRejected("سند برداشت اعتبار اصلی پیدا نشد.")
        await ShopWalletService.apply(
            session,
            identity_id=identity.id,
            forced_account_id=debit.account_id,
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
