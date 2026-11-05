"""Explicit adapters reuse existing Store/Bot/customer commerce services."""

from __future__ import annotations

from sqlalchemy import func, select

from channels.contracts import InboundEvent, Platform
from models.shop_checkout import ShopCartItem
from models.shop_content import Product, ShopCategory, ShopOrder
from models.shop_uom import ShopUom
from services.shop_actions.contracts import ActionRejected
from services.shop_bot_catalog_acl import (
    allowed_for_bot,
    permitted_product_clause,
    resolve_scope,
)
from services.shop_cart import (
    CartRejected,
    CartRevisionConflict,
    ShopCartFlow,
    telegram_stars_total,
    validate_checkout_types,
)
from services.shop_checkout_policy import checkout_rules
from services.shop_customer_orders import (
    order_owner_clause,
    order_visible_to_customer,
    verified_identity_keys,
)
from services.shop_customer_search import query_products
from services.shop_money import to_rials


def _event(principal) -> InboundEvent:
    """Use only the authenticated private customer's own Bot identity."""
    return InboundEvent(
        platform=Platform(principal.platform),
        user_id=principal.platform_user_id,
        chat_id=principal.platform_user_id,
    )


def _flow(principal) -> ShopCartFlow:
    """Attach the same verified BotContext used by existing channel handlers."""
    return ShopCartFlow(bot_context=principal.bot)


async def _unit(db, principal, product) -> dict:
    """Resolve the existing exact sales unit in the product's owning Store."""
    unit = await db.get(ShopUom, product.uom_id)
    if unit is None or unit.store_id != principal.store_id or not unit.active:
        raise ActionRejected("action_uom_unavailable")
    return {
        "id": unit.id,
        "name": unit.name,
        "symbol": unit.symbol,
        "ratio_num": unit.ratio_num,
        "ratio_den": unit.ratio_den,
        "rounding": str(unit.rounding),
    }


async def _product(db, principal, product_id) -> Product:
    """Apply the authoritative ACL before resolving a public product record."""
    if not await allowed_for_bot(db, principal.bot_id, [product_id]):
        raise ActionRejected("action_product_unavailable")
    product = await db.get(Product, product_id)
    if product is None or product.store_id != principal.store_id:
        raise ActionRejected("action_product_unavailable")
    return product


async def _public_product(db, principal, product, *, summary=False):
    """Return typed public values, omitting file paths and private provider data."""
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "description": (product.description or "")[: 200 if summary else 4000],
        "product_type": product.product_type,
        "price_irr": to_rials(product.price),
        "price_stars": product.price_stars,
        "in_stock": product.stock_quantity > 0,
        "uom": await _unit(db, principal, product),
    }


async def list_categories(db, principal, data):
    """Reuse the same published-category/entitled-product SQL predicate as CatalogFlow."""
    scope = await resolve_scope(db, bot_id=principal.bot_id)
    entitled = (
        select(Product.id)
        .where(Product.category_id == ShopCategory.id, permitted_product_clause(scope))
        .correlate(ShopCategory)
        .exists()
    )
    conditions = (
        ShopCategory.store_id == principal.store_id,
        ShopCategory.is_published.is_(True),
        entitled,
    )
    total = int(
        await db.scalar(
            select(func.count()).select_from(ShopCategory).where(*conditions)
        )
        or 0
    )
    page = min(data.page, max(1, (total + data.page_size - 1) // data.page_size))
    rows = (
        await db.scalars(
            select(ShopCategory)
            .where(*conditions)
            .order_by(
                ShopCategory.position,
                ShopCategory.id,
            )
            .offset((page - 1) * data.page_size)
            .limit(data.page_size)
        )
    ).all()
    return {
        "items": [{"id": row.id, "name": row.name} for row in rows],
        "total": total,
        "page": page,
        "has_more": page * data.page_size < total,
    }


async def search_products(db, principal, data):
    """Use the shared customer search service without its chat form state."""
    rows, total, page = await query_products(
        db,
        principal.bot,
        query=data.query,
        field_name=data.field,
        page=data.page,
        page_size=data.page_size,
        category_id=data.category_id,
    )
    return {
        "items": [
            await _public_product(db, principal, row, summary=True) for row in rows
        ],
        "total": total,
        "page": page,
        "has_more": page * data.page_size < total,
    }


async def get_product(db, principal, data):
    """Resolve a single product through the live Bot entitlement service."""
    return await _public_product(
        db, principal, await _product(db, principal, data.product_id)
    )


async def product_visibility(db, principal, data):
    """Do not reveal whether a denied product exists in another Store."""
    return {"visible": await allowed_for_bot(db, principal.bot_id, [data.product_id])}


async def price_uom(db, principal, data):
    """Read native price values and exact existing UoM without currency conversion."""
    product = await _product(db, principal, data.product_id)
    return {
        "product_id": product.id,
        "price_irr": to_rials(product.price),
        "price_stars": product.price_stars,
        "uom": await _unit(db, principal, product),
    }


async def cart_get(db, principal, _data):
    """Reuse the current cart quote and never create a cart while reading."""
    flow = _flow(principal)
    cart = await flow._get_cart(_event(principal), db)
    output = {
        "cart_id": cart.id if cart else None,
        "revision": cart.revision if cart else 0,
        "items": [],
        "subtotal_irr": 0,
        "discount_irr": 0,
        "shipping_irr": 0,
        "total_irr": 0,
        "shipping_required": False,
        "shipping_ready": False,
    }
    count = await db.scalar(
        select(func.count())
        .select_from(ShopCartItem)
        .where(ShopCartItem.cart_id == cart.id if cart else False)
    )
    if not count:
        return output
    try:
        quote = await flow._quote(cart, db, bot_id=principal.bot_id)
    except CartRejected:
        # Stale stock/ACL/coupon/shipping may prevent a quote, but must not
        # roll back a valid removal or trap the customer in an invalid cart.
        # Return owned line IDs only; denied product names/prices remain private.
        rows = (
            await db.scalars(
                select(ShopCartItem)
                .where(
                    ShopCartItem.cart_id == cart.id,
                )
                .order_by(ShopCartItem.id)
            )
        ).all()
        output.update(
            quote_available=False,
            quote_error="action_cart_rejected",
            unquoted_items=[
                {"product_id": row.product_id, "quantity": row.quantity} for row in rows
            ],
            subtotal_irr=None,
            discount_irr=None,
            shipping_irr=None,
            total_irr=None,
            shipping_ready=False,
        )
        return output
    output.update(
        subtotal_irr=quote.subtotal,
        discount_irr=quote.discount,
        shipping_irr=quote.shipping,
        total_irr=quote.total,
        shipping_required=quote.shipping_required,
        shipping_ready=not quote.shipping_required
        or bool(cart.shipping_address and quote.shipping_label),
    )
    output["items"] = [
        {
            "product_id": line.product.id,
            "name": line.product.name,
            "quantity": line.quantity,
            "unit_price_irr": to_rials(line.product.price),
            "line_total_irr": line.line_total,
            "uom": await _unit(db, principal, line.product),
        }
        for line in quote.lines
    ]
    return output


async def _cart_change(db, principal, data, action, *, preview=False):
    """Share validation and flush-only mutations with the existing channel flow."""
    flow, event = _flow(principal), _event(principal)
    kwargs = {
        "quantity": getattr(data, "quantity", 1),
        "expected_revision": getattr(data, "expected_cart_revision", None),
    }
    try:
        if preview:
            await flow.plan_item_change(event, db, action, data.product_id, **kwargs)
            return None
        await flow.mutate_item(event, db, action, data.product_id, **kwargs)
        return await cart_get(db, principal, None)
    except CartRevisionConflict:
        raise ActionRejected("action_cart_revision_conflict") from None
    except CartRejected:
        raise ActionRejected("action_cart_rejected") from None


async def cart_add(db, principal, data):
    """Add exactly the requested whole-unit amount in the owning transaction."""
    return await _cart_change(db, principal, data, "add")


async def cart_add_preview(db, principal, data):
    """Read actual stock/ACL/limits while leaving every SQL row unchanged."""
    return await _cart_change(db, principal, data, "add", preview=True)


async def cart_update(db, principal, data):
    """Set an absolute quantity against the reviewed cart revision."""
    return await _cart_change(db, principal, data, "set")


async def cart_update_preview(db, principal, data):
    """Validate an absolute quantity change without issuing UPDATE/INSERT/DELETE."""
    return await _cart_change(db, principal, data, "set", preview=True)


async def cart_remove(db, principal, data):
    """Remove the selected owned line against its exact cart revision."""
    return await _cart_change(db, principal, data, "remove")


async def cart_remove_preview(db, principal, data):
    """Check a removal without deleting anything."""
    return await _cart_change(db, principal, data, "remove", preview=True)


async def cart_clear_preview(db, principal, data):
    """Validate the exact confirmed cart state without acquiring write state."""
    flow, event = _flow(principal), _event(principal)
    cart = await flow._get_cart(event, db)
    if cart is None or cart.revision != data.expected_cart_revision:
        raise ActionRejected("action_cart_revision_conflict")
    if await flow._existing_pending(db, cart, event) is not None:
        raise ActionRejected("action_cart_rejected")
    return None


async def cart_clear(db, principal, data):
    """The invocation policy consumes confirmation atomically with this clear."""
    try:
        await _flow(principal).clear_cart(
            _event(principal), db, expected_revision=data.expected_cart_revision
        )
    except CartRevisionConflict:
        raise ActionRejected("action_cart_revision_conflict") from None
    except CartRejected:
        raise ActionRejected("action_cart_rejected") from None
    return await cart_get(db, principal, None)


def _order_status(order):
    """Honor original native payment snapshots without exposing payment secrets."""
    currency = order.payment_currency or (
        "XTR" if order.total_stars_snapshot else "IRR"
    )
    amount = (
        order.payment_amount
        if order.payment_amount is not None
        else (order.total_stars_snapshot if currency == "XTR" else order.total_irr)
    )
    return {
        "order_id": order.id,
        "status": order.status,
        "currency": currency,
        "amount": amount,
        "bot_id": order.bot_id,
        "platform": order.platform,
    }


async def customer_orders(db, principal, data):
    """Preserve historical reads across explicitly verified linked Bot identities."""
    keys = await verified_identity_keys(
        db, store_id=principal.store_id, customer_id=principal.customer_id
    )
    clause = order_owner_clause(store_id=principal.store_id, identity_keys=keys)
    total = int(
        await db.scalar(select(func.count()).select_from(ShopOrder).where(clause)) or 0
    )
    page = min(data.page, max(1, (total + data.page_size - 1) // data.page_size))
    rows = (
        await db.scalars(
            select(ShopOrder)
            .where(clause)
            .order_by(ShopOrder.id.desc())
            .offset((page - 1) * data.page_size)
            .limit(data.page_size)
        )
    ).all()
    return {
        "items": [_order_status(row) for row in rows],
        "total": total,
        "page": page,
        "has_more": page * data.page_size < total,
    }


async def order_status(db, principal, data):
    """Resolve orders by verified customer ownership, never numeric user ID alone."""
    order = await order_visible_to_customer(
        db,
        store_id=principal.store_id,
        customer_id=principal.customer_id,
        order_id=data.order_id,
    )
    if order is None:
        raise ActionRejected("action_order_unavailable")
    return _order_status(order)


async def checkout_prepare(db, principal, _data):
    """Calculate real requirements without creating orders, reserving stock or paying."""
    from services.shop_digital_catalog import require_digital_supply
    from services.shop_digital_rules import DeliveryPolicyError
    from services.shop_mixed_checkout_orders import mixed_quote
    from services.shop_mixed_checkout import MixedCheckoutError

    flow, event = _flow(principal), _event(principal)
    cart = await flow._get_cart(event, db)
    policy = await checkout_rules(db, bot_id=principal.bot_id)
    missing = []
    output = {
        "ready": False,
        "missing": missing,
        "cart_revision": cart.revision if cart else 0,
        "mode": policy.mode,
        "terms_version": policy.terms_version,
        "total_irr": None,
        "total_stars": None,
    }
    if not policy.terms_text or not policy.terms_version:
        missing.append("terms")
    if cart is None:
        missing.append("cart")
        return output
    if await flow._existing_pending(db, cart, event) is not None:
        missing.append("pending_order")
    try:
        quote = await flow._quote(cart, db, bot_id=principal.bot_id)
        validate_checkout_types(event.platform, quote)
        if quote.shipping_required:
            if not cart.shipping_address:
                missing.append("shipping_address")
            if not quote.shipping_label:
                missing.append("shipping_method")
        for line in quote.lines:
            if line.product.product_type == "digital":
                await require_digital_supply(
                    db, product=line.product, quantity=line.quantity
                )
        mixed = principal.platform == "telegram" and {
            line.product.product_type for line in quote.lines
        } == {"physical", "digital"}
        if mixed:
            plan, _ = await mixed_quote(
                db, cart=cart, quote=quote, policy_token=policy.policy_token
            )
            output["total_irr"] = plan.physical.total_irr
            output["total_stars"] = plan.digital.total_stars
        else:
            stars = telegram_stars_total(event.platform, quote)
            output["total_stars"] = stars
            output["total_irr"] = None if stars is not None else quote.total
    except (CartRejected, DeliveryPolicyError, OSError, MixedCheckoutError):
        missing.append("cart_or_delivery")
    output["ready"] = not missing
    return output


async def support_preview(db, principal, data):
    """Validate private support text and order ownership without opening a ticket."""
    from services.shop_customer_support import validate_ticket_body

    try:
        validate_ticket_body(data.body)
    except ValueError:
        raise ActionRejected("action_invalid_input") from None
    if data.order_id is not None:
        await order_status(db, principal, data)
    return None


async def support_create(db, principal, data):
    """Reuse flush-only support creation; receipt and private body commit atomically."""
    from services.shop_customer_account import customer_for_bot
    from services.shop_customer_support import (
        append_customer_message,
        create_ticket_record,
    )

    await support_preview(db, principal, data)
    identity, customer = await customer_for_bot(
        db, principal.bot, platform_user_id=principal.platform_user_id
    )
    ticket = await create_ticket_record(
        db,
        principal.bot,
        identity=identity,
        customer_id=customer.id,
        topic=data.topic,
        order_id=data.order_id,
    )
    await append_customer_message(
        db, principal.bot, ticket=ticket, identity=identity, body=data.body
    )
    return {"ticket_id": ticket.id, "status": ticket.status}
