"""Atomic, immutable Telegram mixed-cart checkout into two linked Orders.

The customer approves one bounded quote, but the provider receives two
independent invoices: a physical IRR Order and a digital Stars/XTR Order.
Coupon and shipping affect only the IRR Order. There is no provider call
in the transaction, so a partial database commit cannot charge the user.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import InboundEvent, Platform
from models.shop_checkout import (
    ShopCart, ShopCheckoutGroup, ShopCoupon, ShopOrderLine,
)
from models.shop_content import ShopOrder
from models.shop_uom import ShopUom
from services.shop_checkout_policy import CheckoutRules
from services.shop_mixed_checkout import (
    MixedCheckoutPlan, MixedCheckoutError, build_split_plan,
    checkout_quote_fingerprint,
)


def checkout_idempotency_key(
    *, bot_id: str, user_id: int, cart_id: int, revision: int,
) -> str:
    """Return a fixed-width key that fits the database and is never user input."""
    if (
        not bot_id or type(user_id) is not int or user_id <= 0
        or type(cart_id) is not int or cart_id <= 0
        or type(revision) is not int or revision <= 0
    ):
        raise MixedCheckoutError("Invalid checkout owner or revision.")
    payload = f"checkout-v2:{bot_id}:{user_id}:{cart_id}:{revision}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def mixed_quote(
    db: AsyncSession, *, cart: ShopCart, quote,
    policy_token: str,
) -> tuple[MixedCheckoutPlan, str]:
    """Compute IRR coupon only over physical lines and frozen XTR over digital."""
    from services.shop_cart import validate_coupon

    physical_subtotal = sum(
        line.line_total for line in quote.lines
        if line.product.product_type == "physical"
    )
    discount = 0
    if cart.coupon_id is not None:
        coupon = await db.get(ShopCoupon, cart.coupon_id)
        if coupon is None or coupon.store_id != cart.store_id:
            raise MixedCheckoutError("Coupon belongs to another Store.")
        # Coupon may have been valid against mixed total but fail the
        # physical-only minimum. Never price it using the digital half.
        discount = validate_coupon(coupon, physical_subtotal)
    plan = build_split_plan(
        quote.lines, shipping_irr=quote.shipping,
        physical_discount_irr=discount, coupon_code=quote.coupon_code,
        shipping_label=quote.shipping_label,
    )
    proof = checkout_quote_fingerprint(
        quote.lines, shipping_irr=plan.physical.shipping_irr,
        physical_discount_irr=plan.physical.discount_irr,
        coupon_code=plan.coupon_code,
        shipping_label=plan.shipping_label,
        shipping_address=cart.shipping_address,
        policy_token=policy_token,
    )
    return plan, proof


async def existing_split_orders(
    db: AsyncSession, *, checkout_key: str, bot_id: str,
    store_id: str, user_id: int,
) -> tuple[ShopOrder, ShopOrder] | None:
    """Idempotent response only for the same authenticated buyer and Store."""
    group = await db.scalar(select(ShopCheckoutGroup).where(
        ShopCheckoutGroup.checkout_key == checkout_key,
        ShopCheckoutGroup.bot_id == bot_id,
        ShopCheckoutGroup.store_id == store_id,
        ShopCheckoutGroup.platform_user_id == user_id,
    ))
    if group is None:
        return None
    rows = (await db.scalars(select(ShopOrder).where(
        ShopOrder.checkout_group_id == group.id,
        ShopOrder.bot_id == bot_id,
        ShopOrder.store_id == store_id,
        ShopOrder.platform_user_id == user_id,
    ).order_by(ShopOrder.checkout_part_kind))).all()
    by_kind = {row.checkout_part_kind: row for row in rows}
    if set(by_kind) != {"physical", "digital"}:
        raise MixedCheckoutError("Incomplete split checkout requires review.")
    return by_kind["physical"], by_kind["digital"]


async def create_split_orders(
    db: AsyncSession, *, cart: ShopCart, quote,
    event: InboundEvent, policy: CheckoutRules, bot_id: str,
    checkout_key: str, proof: str,
) -> tuple[ShopOrder, ShopOrder]:
    """Snapshot both Orders under the caller's locked cart transaction.

    Caller must commit once *after* both Orders and all Lines are inserted.
    On any failure, rollback; do not issue an invoice or mutate cart items.
    """
    if event.platform != Platform.TELEGRAM or cart.platform != "telegram":
        raise MixedCheckoutError("Split checkout is Telegram-only.")
    if (
        cart.store_id != policy.store_id or bot_id != policy.bot_id
        or cart.bot_id != bot_id and not cart.is_shared
    ):
        raise MixedCheckoutError("Split Checkout Bot/Store ownership mismatch.")
    plan, current_proof = await mixed_quote(
        db, cart=cart, quote=quote, policy_token=policy.policy_token,
    )
    if current_proof != proof:
        raise MixedCheckoutError(
            "Mixed checkout prices/terms changed; customer approval expired."
        )
    if (
        quote.shipping_required
        and (not cart.shipping_address or not quote.shipping_label)
    ):
        raise MixedCheckoutError("Physical shipment address/method is required.")

    # UoM identifiers remain Store-owned even for physically separate invoices.
    needed_uoms = {line.product.uom_id for line in quote.lines}
    units = dict((await db.execute(select(ShopUom.id, ShopUom.code).where(
        ShopUom.id.in_(needed_uoms),
        ShopUom.store_id == cart.store_id,
    ))).all())
    if len(units) != len(needed_uoms):
        raise MixedCheckoutError("Invalid Store UoM reference.")
    current = {line.product.id: line.product for line in quote.lines}
    group = ShopCheckoutGroup(
        id=str(uuid4()), store_id=cart.store_id,
        bot_id=bot_id, platform_user_id=event.user_id,
        cart_id=cart.id, checkout_key=checkout_key,
        quote_fingerprint=current_proof,
        terms_version_snapshot=policy.terms_version,
    )
    db.add(group)
    # Ensure a duplicate concurrent callback hits the group uniqueness
    # constraint before any Order or stock/payment state is created.
    await db.flush()

    parts = (plan.physical, plan.digital)
    placed: list[ShopOrder] = []
    for part in parts:
        first = part.lines[0]
        first_product = current[first.product_id]
        order = ShopOrder(
            store_id=cart.store_id,
            customer_id=cart.customer_id,
            bot_id=bot_id, platform="telegram",
            platform_user_id=event.user_id, chat_id=event.chat_id,
            checkout_group_id=group.id,
            checkout_part_kind=part.kind,
            product_id=first.product_id,
            product_name_snapshot=first_product.name,
            quantity=first.quantity,
            unit_price_irr=first.unit_price_irr,
            total_irr=part.total_irr,
            total_stars_snapshot=part.total_stars,
            provider="manual_review",
            status=(
                "approved_unpaid" if policy.mode == "instant"
                else "pending_review"
            ),
            terms_version_snapshot=policy.terms_version,
            terms_accepted_at=datetime.now(timezone.utc),
            invoice_payload=secrets.token_urlsafe(32),
            checkout_key=f"{checkout_key}:{'p' if part.kind == 'physical' else 'd'}",
            subtotal_irr=part.subtotal_irr,
            discount_irr=part.discount_irr,
            shipping_irr=part.shipping_irr,
            shipping_address=(
                cart.shipping_address if part.kind == "physical" else None
            ),
            shipping_method_snapshot=(
                plan.shipping_label if part.kind == "physical" else None
            ),
            coupon_code_snapshot=(
                plan.coupon_code if part.kind == "physical" else None
            ),
            coupon_id=cart.coupon_id if part.kind == "physical" else None,
        )
        db.add(order)
        await db.flush()
        for line in part.lines:
            product = current[line.product_id]
            db.add(ShopOrderLine(
                order_id=order.id, product_id=line.product_id,
                product_name_snapshot=product.name,
                sku_snapshot=product.sku,
                uom_code_snapshot=units[product.uom_id],
                unit_price_irr=line.unit_price_irr,
                unit_price_stars_snapshot=(
                    line.unit_price_stars if part.kind == "digital" else None
                ),
                quantity=line.quantity,
                total_irr=line.line_total_irr,
            ))
        placed.append(order)
    await db.flush()
    return placed[0], placed[1]
