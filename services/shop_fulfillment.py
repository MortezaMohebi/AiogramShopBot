"""Safe Store-owned physical shipment and digital-delivery state machine.

No shipment status mutates the paid/refund state. Digital delivery is only a
recorded verification event after a successfully reconciled payment; actual
license/file sending requires the reviewed secure media delivery subsystem.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import Product, ShopOrder
from models.shop_checkout import ShopOrderLine
from models.shop_customer_support import ShopFulfillmentEvent, ShopOrderFulfillment


_PHYSICAL_NEXT = {
    "processing": "ready",
    "ready": "shipped",
    "shipped": "delivered",
}
_DIGITAL_NEXT = {
    "processing": "delivered",
}


def validate_fulfillment_transition(
    current: str, next_status: str,
    *, physical: bool, paid: bool,
) -> bool:
    """Only permit forward transitions after confirmed payment settlement."""
    if not paid:
        raise ValueError("A paid receipt is required before fulfillment.")
    if not physical:
        # No secure license/file delivery confirmation is connected yet.
        # Marking a paid digital Order delivered here would falsely claim
        # that the customer received an asset. Keep it in processing.
        raise ValueError(
            "Digital delivery requires a verified secure asset receipt."
        )
    allowed = _PHYSICAL_NEXT
    if allowed.get(current) != next_status:
        raise ValueError("Invalid or out-of-order fulfillment transition.")
    return True


async def ensure_fulfillment(
    db: AsyncSession, *, order_id: int, store_id: str,
) -> ShopOrderFulfillment:
    """Create the first fulfillment record for a paid Store-owned Order."""
    order = await db.scalar(select(ShopOrder).where(
        ShopOrder.id == order_id,
        ShopOrder.store_id == store_id,
    ).with_for_update())
    if order is None or order.status != "paid":
        raise ValueError("Fulfillment requires a settled, paid Order.")
    rows = (await db.scalars(select(Product.product_type).join(
        ShopOrderLine, ShopOrderLine.product_id == Product.id,
    ).where(ShopOrderLine.order_id == order.id))).all()
    types = set(rows)
    if len(types) != 1 or not types <= {"digital", "physical"}:
        raise ValueError("Mixed/unknown Order fulfillment is not supported.")
    existing = await db.scalar(select(ShopOrderFulfillment).where(
        ShopOrderFulfillment.order_id == order_id,
        ShopOrderFulfillment.store_id == store_id,
    ).with_for_update())
    if existing is not None:
        return existing
    row = ShopOrderFulfillment(
        store_id=store_id, order_id=order_id,
        kind=types.pop(), status="processing",
    )
    db.add(row)
    await db.flush()
    return row


async def advance_fulfillment(
    db: AsyncSession, *, order_id: int, store_id: str,
    next_status: str, expected_version: int, actor_id: int,
    carrier: str | None = None,
    tracking_code: str | None = None,
) -> dict:
    """Record one verified, staff-authorized, monotonic fulfillment step."""
    record = await ensure_fulfillment(
        db, order_id=order_id, store_id=store_id,
    )
    if record.version != expected_version:
        raise ValueError("Fulfillment record was changed by another operator.")
    validate_fulfillment_transition(
        record.status, next_status,
        physical=record.kind == "physical", paid=True,
    )
    if record.kind == "physical" and next_status == "shipped":
        if (
            not carrier or not 1 <= len(carrier.strip()) <= 80
            or not tracking_code or not 1 <= len(tracking_code.strip()) <= 120
        ):
            raise ValueError("Physical shipment requires carrier/tracking code.")
        record.carrier = carrier.strip()
        record.tracking_code = tracking_code.strip()
    previous = record.status
    record.status = next_status
    record.version += 1
    db.add(ShopFulfillmentEvent(
        store_id=store_id, fulfillment_id=record.id,
        previous_status=previous, next_status=next_status,
        actor_id=actor_id,
    ))
    await db.commit()
    return {
        "id": record.id,
        "order_id": record.order_id, "status": record.status,
        "kind": record.kind, "version": record.version,
    }


async def customer_tracking(
    db: AsyncSession, *, order: ShopOrder,
) -> dict:
    """Read authenticated Order tracking without inventing delivery events."""
    record = await db.scalar(select(ShopOrderFulfillment).where(
        ShopOrderFulfillment.order_id == order.id,
        ShopOrderFulfillment.store_id == order.store_id,
    ))
    if record is None:
        return {
            "order_id": order.id,
            "status": "not_started",
            "message": "هنوز رویداد انجام یا ارسال برای این سفارش ثبت نشده است.",
        }
    events = (await db.scalars(select(ShopFulfillmentEvent).where(
        ShopFulfillmentEvent.fulfillment_id == record.id,
        ShopFulfillmentEvent.store_id == order.store_id,
    ).order_by(ShopFulfillmentEvent.id).limit(30))).all()
    return {
        "order_id": order.id,
        "status": record.status, "kind": record.kind,
        "carrier": record.carrier, "tracking_code": record.tracking_code,
        "events": [{
            "status": item.next_status,
            "time": item.recorded_at.isoformat(),
        } for item in events],
    }
