"""Bale wallet purchase processing with verified, idempotent order updates.

Bale's wallet is the payment **provider**, not our local cryptocurrency wallet.
Prices are stored as integer IRR and must never be treated as toman at API time.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from channels.bale import BaleTransport
from models.shop_content import Product, ShopOrder
from services.shop_money import to_rials


class CheckoutRejected(ValueError):
    """A safe customer-facing refusal to create or complete an order."""


def _positive_id(value: Any) -> int | None:
    """Parse a real platform user ID, never a Python boolean."""
    return value if type(value) is int and value > 0 else None


class BaleWalletService:
    """Connect native Bale payment events with the shared shop order ledger."""

    @staticmethod
    async def create_invoice(
        session: AsyncSession,
        transport: BaleTransport,
        *,
        product_id: int,
        platform_user_id: int,
        chat_id: int,
        provider_token: str,
    ) -> ShopOrder:
        """Create one pending order and then ask Bale to charge its wallet.

        A failure to send the invoice leaves an *unpaid* order; a successful
        charge can only be recorded by the verified callback handler.
        """
        if not provider_token:
            raise CheckoutRejected("پرداخت کیف پول بله هنوز فعال نشده است.")
        if _positive_id(platform_user_id) is None or _positive_id(chat_id) is None:
            raise CheckoutRejected("شناسه خریدار نامعتبر است.")

        product = await session.scalar(
            select(Product).where(
                Product.id == product_id,
                Product.is_published.is_(True),
            )
        )
        if product is None or product.stock_quantity < 1:
            raise CheckoutRejected("این محصول در حال حاضر موجود نیست.")
        rial_price = to_rials(product.price)
        if rial_price == 0:
            raise CheckoutRejected("قیمت این محصول برای پرداخت معتبر نیست.")

        # Payload is unpredictable, unique, and within Bale's 128-byte limit.
        order = ShopOrder(
            platform="bale",
            platform_user_id=platform_user_id,
            chat_id=chat_id,
            product_id=product.id,
            product_name_snapshot=product.name,
            quantity=1,
            unit_price_irr=rial_price,
            total_irr=rial_price,
            provider="bale_wallet",
            status="pending_payment",
            invoice_payload=secrets.token_urlsafe(32),
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)
        await transport.send_invoice(
            chat_id=chat_id,
            title=product.name[:32],
            description=product.description[:255] or product.name[:255],
            payload=order.invoice_payload,
            provider_token=provider_token,
            amount_irr=order.total_irr,
        )
        return order

    @staticmethod
    async def validate_pre_checkout(
        session: AsyncSession,
        query: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        """Confirm price, buyer, currency and stock without accepting payment.

        Approval is deliberately *not* a stock reservation; the final,
        transaction-safe check happens only after payment confirmation.
        """
        payer = query.get("from")
        if not isinstance(payer, Mapping):
            return False, "اطلاعات خریدار ناقص است."
        user_id = _positive_id(payer.get("id"))
        currency = query.get("currency")
        amount = query.get("total_amount")
        payload = query.get("invoice_payload")
        if (
            user_id is None or currency != "IRR"
            or type(amount) is not int
            or not isinstance(payload, str)
            or not 1 <= len(payload) <= 128
        ):
            return False, "مشخصات پرداخت نامعتبر است."

        record = await session.execute(
            select(ShopOrder, Product)
            .join(Product, ShopOrder.product_id == Product.id)
            .where(
                ShopOrder.invoice_payload == payload,
                ShopOrder.platform == "bale",
            )
        )
        row = record.one_or_none()
        if row is None:
            return False, "سفارش یافت نشد."
        order, product = row
        if order.platform_user_id != user_id or order.total_irr != amount:
            return False, "مبلغ یا خریدار با سفارش مطابقت ندارد."
        if order.status != "pending_payment":
            return False, "این سفارش دیگر قابل پرداخت نیست."
        if not product.is_published or product.stock_quantity < order.quantity:
            return False, "موجودی کالا برای این سفارش کافی نیست."
        return True, None

    @staticmethod
    async def confirm_success(
        session: AsyncSession,
        transport: BaleTransport,
        *,
        payer_id: int,
        chat_id: int,
        payment: Mapping[str, Any],
    ) -> tuple[ShopOrder, bool]:
        """Verify Bale's receipt and inquiry, then fulfill an order once.

        The transaction ID and exact paid amount are corroborated through
        inquireTransaction before mutating inventory or payment state.
        Duplicate callbacks return `changed=False` and do not decrement twice.
        """
        payload = payment.get("invoice_payload")
        transaction_id = payment.get("telegram_payment_charge_id")
        provider_id = payment.get("provider_payment_charge_id")
        amount = payment.get("total_amount")
        if (
            not isinstance(payload, str)
            or not 1 <= len(payload) <= 128
            or not isinstance(transaction_id, str)
            or not 1 <= len(transaction_id) <= 128
            or not isinstance(provider_id, str)
            or not 1 <= len(provider_id) <= 128
            or payment.get("currency") != "IRR"
            or type(amount) is not int
            or _positive_id(payer_id) is None
            or _positive_id(chat_id) is None
        ):
            raise CheckoutRejected("اطلاعات رسید پرداخت نامعتبر است.")

        # Validate independent provider evidence *before* database settlement.
        evidence = await transport.inquire_transaction(transaction_id)
        if (
            evidence.get("status") != "paid"
            or _positive_id(evidence.get("userID")) != payer_id
            or type(evidence.get("amount")) is not int
            or evidence["amount"] != amount
            or str(evidence.get("id")) != transaction_id
        ):
            raise CheckoutRejected("استعلام پرداخت کیف پول بله تأیید نشد.")

        # Lock the order so concurrent retries cannot fulfill twice.
        result = await session.execute(
            select(ShopOrder).where(
                ShopOrder.invoice_payload == payload,
                ShopOrder.platform == "bale",
            ).with_for_update()
        )
        order = result.scalar_one_or_none()
        if (
            order is None
            or order.platform_user_id != payer_id
            or order.chat_id != chat_id
            or order.total_irr != amount
            or order.provider != "bale_wallet"
        ):
            raise CheckoutRejected("رسید با سفارش مطابقت ندارد.")

        if order.status in ("paid", "paid_unfulfilled"):
            if (
                order.telegram_payment_charge_id != transaction_id
                or order.provider_payment_charge_id != provider_id
            ):
                raise CheckoutRejected("این سفارش قبلاً با رسید دیگری پرداخت شده است.")
            return order, False
        if order.status != "pending_payment":
            raise CheckoutRejected("سفارش امکان تأیید پرداخت ندارد.")

        # Atomic stock allocation under concurrency, even when two different
        # orders finish payment in the same second.
        inventory = await session.execute(
            update(Product)
            .where(
                Product.id == order.product_id,
                Product.stock_quantity >= order.quantity,
            )
            .values(stock_quantity=Product.stock_quantity - order.quantity)
        )
        order.status = "paid" if inventory.rowcount == 1 else "paid_unfulfilled"
        order.telegram_payment_charge_id = transaction_id
        order.provider_payment_charge_id = provider_id
        order.paid_at = datetime.now(timezone.utc)
        await session.commit()
        return order, True

    @staticmethod
    async def list_orders(
        session: AsyncSession, *, platform: str, platform_user_id: int
    ) -> str:
        """Show the customer's latest purchases without leaking other accounts."""
        result = await session.execute(
            select(ShopOrder)
            .where(
                ShopOrder.platform == platform,
                ShopOrder.platform_user_id == platform_user_id,
            )
            .order_by(ShopOrder.id.desc())
            .limit(10)
        )
        orders = result.scalars().all()
        if not orders:
            return "هنوز سفارشی ثبت نکرده‌اید."
        labels = {
            "pending_review": "در انتظار بررسی فروشنده",
            "pending_payment": "در انتظار پرداخت",
            "paid": "پرداخت‌شده",
            "paid_unfulfilled": "پرداخت‌شده؛ در انتظار بررسی موجودی",
            "cancelled": "لغوشده",
        }
        return "📦 سفارش‌های من\n\n" + "\n".join(
            f"#{item.id} — {item.product_name_snapshot}: "
            f"{labels.get(item.status, 'در حال بررسی')}"
            for item in orders
        )
