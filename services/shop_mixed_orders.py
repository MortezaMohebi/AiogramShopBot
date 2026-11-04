"""Atomically convert one verified mixed Telegram cart into two native Orders.

The IRR physical Order and XTR digital Order share a nonfinancial Checkout
Batch identity but NEVER share provider attempts, charge IDs, refunds or
fulfillment. Duplicate callbacks are matched against the locked Cart revision
and unique batch source key; an error rolls back both Order inserts.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_checkout import (
    ShopCart, ShopCartInputSession, ShopCartItem, ShopOrderLine,
)
from models.shop_checkout_batch import ShopCheckoutBatch
from models.shop_content import ShopOrder
from models.shop_uom import ShopUom
from services.shop_mixed_checkout import MixedCheckoutPlan


def checkout_key(
    *, bot_id: str, user_id: int, cart_id: int, revision: int,
) -> str:
    """Produce a stable, short, unique idempotency key for one Cart revision."""
    raw = f"{bot_id}:{user_id}:{cart_id}:{revision}".encode("ascii")
    return "co:" + hashlib.sha256(raw).hexdigest()[:48]


async def batch_orders(
    db: AsyncSession, *, bot_id: str, cart_id: int, revision: int,
    store_id: str, user_id: int,
) -> list[ShopOrder]:
    """Read a previous batch with the exact trusted source ownership tuple."""
    batch = await db.scalar(select(ShopCheckoutBatch).where(
        ShopCheckoutBatch.bot_id == bot_id,
        ShopCheckoutBatch.cart_id == cart_id,
        ShopCheckoutBatch.cart_revision == revision,
        ShopCheckoutBatch.store_id == store_id,
        ShopCheckoutBatch.platform_user_id == user_id,
    ))
    if batch is None:
        return []
    return list((await db.scalars(select(ShopOrder).where(
        ShopOrder.checkout_batch_id == batch.id,
        ShopOrder.bot_id == bot_id,
        ShopOrder.store_id == store_id,
        ShopOrder.platform_user_id == user_id,
    ).order_by(ShopOrder.checkout_part))).all())


async def create_split_orders(
    db: AsyncSession, *, cart: ShopCart,
    quote, split: MixedCheckoutPlan,
    policy, bot_id: str, user_id: int, chat_id: int,
    expected_revision: int, quote_token: str,
) -> tuple[ShopOrder, ShopOrder]:
    """Save exactly two Orders and clear Cart in one DB transaction.

    Preconditions: live Bot ACL, lock of current Cart, signed customer
    identity, current prices, shipping, coupon and quote proof were
    reverified by ShopCartFlow immediately before this function.
    """
    if (
        cart.store_id != policy.store_id
        or policy.bot_id != bot_id
        or cart.revision != expected_revision
        or not split.physical.lines or not split.digital.lines
    ):
        raise ValueError("Mixed checkout does not match verified Cart owner.")
    batch = ShopCheckoutBatch(
        id=str(uuid4()), store_id=cart.store_id, bot_id=bot_id,
        platform="telegram", platform_user_id=user_id,
        customer_id=cart.customer_id,
        cart_id=cart.id, cart_revision=cart.revision,
        quote_token=quote_token,
        terms_version_snapshot=policy.terms_version,
    )
    db.add(batch)
    await db.flush()
    selected_units = {line.product.uom_id for line in quote.lines}
    unit_codes = dict((await db.execute(select(
        ShopUom.id, ShopUom.code,
    ).where(
        ShopUom.id.in_(selected_units),
        ShopUom.store_id == cart.store_id,
    ))).all())
    if len(unit_codes) != len(selected_units):
        raise ValueError("Product unit belongs to an invalid Store.")
    live_items = {line.product.id: line for line in quote.lines}
    orders: list[ShopOrder] = []

    for part, suffix in (
        (split.physical, "p"),
        (split.digital, "d"),
    ):
        selected = [live_items[item.product_id] for item in part.lines]
        first = selected[0]
        requires_shipping = (
            part.kind == "physical"
            and any(line.product.requires_shipping for line in selected)
        )
        order = ShopOrder(
            store_id=cart.store_id,
            customer_id=cart.customer_id,
            bot_id=bot_id, platform="telegram",
            platform_user_id=user_id, chat_id=chat_id,
            product_id=first.product.id,
            product_name_snapshot=first.product.name,
            quantity=first.quantity,
            unit_price_irr=first.product.price,
            total_irr=part.total_irr,
            total_stars_snapshot=part.total_stars,
            provider="manual_review",
            status=(
                "approved_unpaid" if policy.mode == "instant"
                else "pending_review"
            ),
            terms_version_snapshot=policy.terms_version,
            terms_accepted_at=datetime.now(timezone.utc),
            checkout_batch_id=batch.id,
            checkout_part=part.kind,
            invoice_payload=secrets.token_urlsafe(32),
            checkout_key=checkout_key(
                bot_id=bot_id, user_id=user_id,
                cart_id=cart.id, revision=expected_revision,
            ) + ":" + suffix,
            subtotal_irr=part.subtotal_irr,
            discount_irr=part.discount_irr,
            shipping_irr=part.shipping_irr,
            shipping_address=(
                cart.shipping_address if requires_shipping else None
            ),
            shipping_method_snapshot=(
                split.shipping_label if requires_shipping else None
            ),
            coupon_code_snapshot=(
                split.coupon_code if part.kind == "physical" else None
            ),
            coupon_id=(
                cart.coupon_id if part.kind == "physical" else None
            ),
        )
        db.add(order)
        await db.flush()
        for line in selected:
            db.add(ShopOrderLine(
                order_id=order.id,
                product_id=line.product.id,
                product_name_snapshot=line.product.name,
                sku_snapshot=line.product.sku,
                uom_code_snapshot=unit_codes[line.product.uom_id],
                unit_price_irr=line.product.price,
                unit_price_stars_snapshot=(
                    line.product.price_stars
                    if part.kind == "digital" else None
                ),
                quantity=line.quantity,
                total_irr=line.line_total,
            ))
        orders.append(order)

    # Remove the original mixed Cart only after BOTH orders are complete.
    # Another callback will find the Batch and cannot cause another charge.
    await db.execute(delete(ShopCartItem).where(
        ShopCartItem.cart_id == cart.id,
    ))
    cart.shipping_address = None
    cart.shipping_method_id = None
    cart.coupon_id = None
    cart.awaiting_input = None
    if cart.is_shared:
        await db.execute(update(ShopCartInputSession).where(
            ShopCartInputSession.cart_id == cart.id,
        ).values(awaiting_input=None))
    cart.revision += 1
    await db.commit()
    return orders[0], orders[1]
