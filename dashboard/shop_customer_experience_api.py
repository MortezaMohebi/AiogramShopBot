"""Signed administrative operations for customer menus, checkout and support.

All resources are Store-scoped. Sensitive menu/payment policy changes require
fresh staff proof. Ticket and fulfillment operations require editor membership
and never bypass provider payment reconciliation or modify customer consent.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from channels.contracts import Platform
from dashboard.admin_control_api import Proof, StrictPayload, fresh_proof
from dashboard.next_api import database, signed_staff
from models.shop_content import Product, ShopIdentity, ShopOrder
from models.shop_customer_account_data import ShopCustomerAddress, ShopCustomerWishlist
from models.shop_customer_notifications import (
    ShopCustomerNotificationOutbox, ShopStockAlert,
)
from models.shop_customer_support import (
    ShopFulfillmentEvent, ShopOrderFulfillment,
    ShopSupportMessage, ShopSupportTicket,
)
from models.shop_multibot import ShopBot
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_checkout_policy as checkout
from services import shop_customer_menu as menu
from services import shop_customer_support as support
from services import shop_customer_notifications as notifications
from services import shop_fulfillment as fulfillment
from services.shop_bot_context import BotContext
from services.shop_store_context import StoreContext

router = APIRouter(prefix="/internal/admin/v1", tags=["Customer Experience"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


def require(
    actor: ShopStaff | None, request: Request, permission: str,
    *, store_id: str | None = None, write: bool = False,
    manage: bool = False,
) -> tuple[ShopStaff, StoreContext]:
    """Validate role, active Store grant and one Store owner for writes."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    scope = getattr(request.state, "store_context", None)
    if not isinstance(scope, StoreContext):
        raise security.SecurityRejected("store_access_denied", 403)
    if store_id is not None:
        scope.require(store_id, write=write, manage=manage)
    elif write:
        scope.require(scope.current_store_id, write=True)
    return actor, scope


class MenuUpdate(Proof):
    """Versioned allowlisted Bot menu buttons, no arbitrary callback values."""

    actions: list[str] = Field(min_length=1, max_length=6)
    expected_version: int = Field(ge=0)


class StoreCheckoutUpdate(Proof):
    """Explicit instant/manual mode and a versioned Store sales policy."""

    expected_version: int = Field(ge=0)
    mode: Literal["manual", "instant"]
    terms_version: str = Field(min_length=1, max_length=32)
    terms_text: str = Field(max_length=6000)


class BotCheckoutUpdate(Proof):
    """Optional Bot-specific mode without overriding Store's sales terms."""

    expected_version: int = Field(ge=0)
    mode_override: Literal["manual", "instant"] | None = None


class StaffTicketReply(StrictPayload):
    """Operational staff reply; no payment or customer-profile permission."""

    expected_version: int = Field(ge=1)
    body: str = Field(min_length=1, max_length=4000)


class ShipmentStep(StrictPayload):
    """Staff-controlled, paid-only physical/digital event transition."""

    expected_version: int = Field(ge=1)
    next_status: Literal["ready", "shipped", "delivered"]
    carrier: str | None = Field(default=None, max_length=80)
    tracking_code: str | None = Field(default=None, max_length=120)


@router.get("/stores/{store_id}/customer-menu")
async def read_store_menu(
    store_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Read one Store's effective six-button base menu."""
    require(actor, request, "bots.read", store_id=str(store_id))
    return await menu.menu_snapshot(db, store_id=str(store_id))


@router.post("/stores/{store_id}/customer-menu")
async def update_store_menu(
    store_id: UUID, payload: MenuUpdate,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Reorder/disable Store menu buttons with MFA; security is independent."""
    staff, _ = require(
        actor, request, "bots.configure",
        store_id=str(store_id), write=True, manage=True,
    )
    await fresh_proof(db, staff, payload)
    return await menu.set_menu(
        db, store_id=str(store_id), actions=payload.actions,
        actor_id=staff.id, expected_version=payload.expected_version,
    )


@router.get("/bot-registry/{bot_id}/customer-menu")
async def read_bot_menu(
    bot_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Read a Bot override or inherited Store customer menu."""
    require(actor, request, "bots.read")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    require(actor, request, "bots.read", store_id=bot.store_id)
    return await menu.menu_snapshot(db, bot_id=bot.id)


@router.post("/bot-registry/{bot_id}/customer-menu")
async def update_bot_menu(
    bot_id: UUID, payload: MenuUpdate,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Persist only a trusted Bot's six-button ordering/visibility."""
    staff, _ = require(actor, request, "bots.configure")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    require(
        actor, request, "bots.configure",
        store_id=bot.store_id, write=True, manage=True,
    )
    await fresh_proof(db, staff, payload)
    return await menu.set_menu(
        db, bot_id=bot.id, actions=payload.actions,
        actor_id=staff.id, expected_version=payload.expected_version,
    )


@router.get("/stores/{store_id}/checkout-policy")
async def read_checkout_policy(
    store_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Show current Store Checkout mode and versioned sales terms."""
    require(actor, request, "bots.read", store_id=str(store_id))
    return await checkout.checkout_policy_snapshot(
        db, store_id=str(store_id),
    )


@router.post("/stores/{store_id}/checkout-policy")
async def update_checkout_policy(
    store_id: UUID, payload: StoreCheckoutUpdate,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Require Store manager and fresh MFA before permitting Instant checkout."""
    staff, _ = require(
        actor, request, "bots.configure", store_id=str(store_id),
        write=True, manage=True,
    )
    await fresh_proof(db, staff, payload)
    return await checkout.save_store_checkout(
        db, store_id=str(store_id),
        actor_id=staff.id, expected_version=payload.expected_version,
        mode=payload.mode,
        terms_version=payload.terms_version,
        terms_text=payload.terms_text,
    )


@router.get("/bot-registry/{bot_id}/checkout-policy")
async def read_bot_checkout(
    bot_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Read one Bot's checkout override with its Store's sales terms."""
    require(actor, request, "bots.read")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    require(actor, request, "bots.read", store_id=bot.store_id)
    return await checkout.checkout_policy_snapshot(
        db, store_id=bot.store_id, bot_id=bot.id,
    )


@router.post("/bot-registry/{bot_id}/checkout-policy")
async def update_bot_checkout(
    bot_id: UUID, payload: BotCheckoutUpdate,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Override only Bot approval mode; Provider rail grants still apply."""
    staff, _ = require(actor, request, "bots.configure")
    bot = await db.get(ShopBot, str(bot_id))
    if bot is None:
        raise security.SecurityRejected("bot_not_found", 404)
    require(
        actor, request, "bots.configure",
        store_id=bot.store_id, write=True, manage=True,
    )
    await fresh_proof(db, staff, payload)
    return await checkout.save_bot_checkout(
        db, bot_id=bot.id, actor_id=staff.id,
        expected_version=payload.expected_version,
        mode_override=payload.mode_override,
    )


@router.get("/store-customers/{customer_id}/addresses")
async def customer_addresses(
    customer_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Read a customer's address list only inside accessible Store scope."""
    require(actor, request, "customers.read")
    from models.shop_store_commerce import ShopStoreCustomer

    customer = await db.get(ShopStoreCustomer, customer_id)
    if customer is None:
        raise security.SecurityRejected("customer_not_found", 404)
    require(actor, request, "customers.read", store_id=customer.store_id)
    rows = (await db.scalars(select(ShopCustomerAddress).where(
        ShopCustomerAddress.store_id == customer.store_id,
        ShopCustomerAddress.customer_id == customer_id,
    ).order_by(ShopCustomerAddress.id).limit(30))).all()
    return {
        "customer_id": customer_id,
        "items": [{
            "id": row.id, "label": row.label, "recipient": row.recipient,
            "phone": row.phone, "province": row.province, "city": row.city,
            "full_address": row.full_address,
            "postal_code": row.postal_code, "is_default": row.is_default,
        } for row in rows],
    }


@router.get("/support-tickets")
async def list_support(
    request: Request, actor: Actor, db: Db,
    status: Literal["open", "pending", "resolved", "closed"] | None = None,
) -> dict:
    """List bounded support queue for the current Store selection."""
    _, ctx = require(actor, request, "customers.read")
    query = select(ShopSupportTicket).where(
        ShopSupportTicket.store_id.in_(ctx.active_store_ids),
    )
    if status:
        query = query.where(ShopSupportTicket.status == status)
    tickets = (await db.scalars(
        query.order_by(ShopSupportTicket.id.desc()).limit(100),
    )).all()
    return {"items": [{
        "id": item.id, "store_id": item.store_id,
        "bot_id": item.bot_id, "customer_id": item.customer_id,
        "status": item.status, "topic": item.topic,
        "version": item.version,
        "created_at": item.created_at.isoformat(),
    } for item in tickets]}


@router.get("/support-tickets/{ticket_id}")
async def support_details(
    ticket_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Read an authorized ticket and its last fifty public conversation notes."""
    _, ctx = require(actor, request, "customers.read")
    ticket = await db.get(ShopSupportTicket, ticket_id)
    if ticket is None:
        raise security.SecurityRejected("ticket_not_found", 404)
    ctx.require(ticket.store_id)
    messages = (await db.scalars(select(ShopSupportMessage).where(
        ShopSupportMessage.ticket_id == ticket.id,
        ShopSupportMessage.store_id == ticket.store_id,
    ).order_by(ShopSupportMessage.id.desc()).limit(50))).all()
    return {
        "id": ticket.id, "store_id": ticket.store_id,
        "bot_id": ticket.bot_id,
        "customer_id": ticket.customer_id,
        "topic": ticket.topic, "status": ticket.status,
        "version": ticket.version,
        "messages": [{
            "id": msg.id, "sender_kind": msg.sender_kind,
            "body": msg.body,
            "created_at": msg.created_at.isoformat(),
        } for msg in reversed(messages)],
    }


@router.post("/support-tickets/{ticket_id}/reply")
async def reply_to_ticket(
    ticket_id: int, payload: StaffTicketReply,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Commit one staff message and its outbox notice in one Store transaction."""
    staff, ctx = require(actor, request, "customers.read", write=True)
    ticket = await db.get(ShopSupportTicket, ticket_id)
    if ticket is None:
        raise security.SecurityRejected("ticket_not_found", 404)
    ctx.require(ticket.store_id, write=True)
    answer = await support.staff_reply(
        db, ticket_id=ticket_id, store_id=ticket.store_id,
        actor_id=staff.id, message=payload.body,
        expected_version=payload.expected_version, commit=False,
    )
    bot = await db.get(ShopBot, ticket.bot_id)
    identity = await db.get(ShopIdentity, ticket.origin_identity_id)
    if bot is None or identity is None or bot.store_id != ticket.store_id:
        raise security.SecurityRejected("ticket_identity_invalid", 409)
    from channels.contracts import Platform
    context = BotContext(
        bot_id=bot.id, store_id=bot.store_id,
        platform=Platform(bot.platform), provider_bot_id=bot.provider_bot_id,
        status=bot.status, runtime_owner=bot.runtime_owner,
        credential_version=bot.credential_version,
        registry_version=bot.version,
    )
    await notifications.enqueue_notification(
        db, context=context,
        user_id=identity.platform_user_id, topic="ticket",
        event_key=f"ticket_reply:{ticket.id}:{answer['version']}",
        body=f"💬 پشتیبانی به درخواست #{ticket.id} شما پاسخ داد. "
             "برای مشاهده پاسخ، «درخواست‌های من» را باز کنید.",
    )
    await db.commit()
    return answer


@router.get("/fulfillments")
async def list_fulfillments(
    request: Request, actor: Actor, db: Db,
) -> dict:
    """List paid Orders and their fulfillment state in accessible Stores."""
    _, ctx = require(actor, request, "orders.read")
    rows = (await db.execute(select(
        ShopOrder, ShopOrderFulfillment,
    ).outerjoin(
        ShopOrderFulfillment, ShopOrderFulfillment.order_id == ShopOrder.id,
    ).where(
        ShopOrder.store_id.in_(ctx.active_store_ids),
        ShopOrder.status == "paid",
    ).order_by(ShopOrder.id.desc()).limit(100))).all()
    return {"items": [{
        "order_id": order.id, "store_id": order.store_id,
        "total_irr": str(order.total_irr),
        "status": record.status if record else "not_started",
        "kind": record.kind if record else None,
        "version": record.version if record else 1,
        "carrier": record.carrier if record else None,
        "tracking_code": record.tracking_code if record else None,
    } for order, record in rows]}


@router.post("/fulfillments/{order_id}/advance")
async def advance_fulfillment(
    order_id: int, payload: ShipmentStep,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Apply one authorized, irreversible forward fulfillment transition."""
    _, ctx = require(actor, request, "orders.manage", write=True)
    order = await db.get(ShopOrder, order_id)
    if order is None:
        raise security.SecurityRejected("order_not_found", 404)
    ctx.require(order.store_id, write=True)
    try:
        return await fulfillment.advance_fulfillment(
            db, order_id=order_id, store_id=order.store_id,
            next_status=payload.next_status,
            expected_version=payload.expected_version,
            actor_id=actor.id,
            carrier=payload.carrier,
            tracking_code=payload.tracking_code,
        )
    except ValueError:
        raise security.SecurityRejected("invalid_fulfillment_step", 409) from None


@router.get("/customer-notifications")
async def notification_overview(
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Observe Store-scoped stock consent and delivery queue health."""
    _, ctx = require(actor, request, "bots.read")
    alerts = (await db.execute(select(
        ShopStockAlert.store_id, ShopStockAlert.status,
        func.count(ShopStockAlert.id),
    ).where(
        ShopStockAlert.store_id.in_(ctx.active_store_ids),
    ).group_by(
        ShopStockAlert.store_id, ShopStockAlert.status,
    ))).all()
    deliveries = (await db.execute(select(
        ShopCustomerNotificationOutbox.store_id,
        ShopCustomerNotificationOutbox.status,
        func.count(ShopCustomerNotificationOutbox.id),
    ).where(
        ShopCustomerNotificationOutbox.store_id.in_(ctx.active_store_ids),
    ).group_by(
        ShopCustomerNotificationOutbox.store_id,
        ShopCustomerNotificationOutbox.status,
    ))).all()
    return {
        "stock_alerts": [
            {"store_id": store, "status": status, "count": count}
            for store, status, count in alerts
        ],
        "delivery_outbox": [
            {"store_id": store, "status": status, "count": count}
            for store, status, count in deliveries
        ],
        "unknown_delivery_requires_review": True,
    }
