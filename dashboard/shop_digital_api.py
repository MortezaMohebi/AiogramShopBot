"""Signed Admin digital inventory, private file upload and receipt inspector.

License plaintext and encrypted payload never enter API responses. A request
cannot set Store ownership, preview another Store asset or download a paid
private file. One product's mode is changed only after a validated supply.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from dashboard.admin_control_api import Proof, fresh_proof
from dashboard.next_api import database, signed_staff
from dashboard.shop_customer_experience_api import require
from models.shop_content import Product, ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services.shop_digital_catalog import (
    add_license_batch, digital_catalog_snapshot, set_private_product_file,
)
from services.shop_digital_rules import DeliveryPolicyError

router = APIRouter(
    prefix="/internal/admin/v1",
    tags=["Private Digital Fulfillment"],
)
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


class DigitalLicenseBatch(Proof):
    """Private one-time license input, never echoed after storage."""

    codes: list[str] = Field(min_length=1, max_length=100)


async def _authorize_product(
    db: AsyncSession, actor: ShopStaff | None, request: Request,
    product_id: int, *, write: bool,
) -> Product:
    """Check active Store grant and real Product owner for every action."""
    require(
        actor, request, "catalog.write" if write else "catalog.read",
        write=write,
    )
    product = await db.get(Product, product_id)
    if product is None:
        raise security.SecurityRejected("catalog_target_not_found", 404)
    require(
        actor, request, "catalog.write" if write else "catalog.read",
        store_id=product.store_id, write=write,
    )
    return product


@router.get("/products/{product_id}/digital-assets")
async def digital_product_snapshot(
    product_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Return file metadata and stock counts only, never secret contents."""
    product = await _authorize_product(
        db, actor, request, product_id, write=False,
    )
    return await digital_catalog_snapshot(
        db, store_id=product.store_id, product_id=product.id,
    )


@router.post("/products/{product_id}/digital-licenses")
async def save_digital_licenses(
    product_id: int, payload: DigitalLicenseBatch,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Import signed and encrypted one-time licenses with fresh MFA proof."""
    product = await _authorize_product(
        db, actor, request, product_id, write=True,
    )
    await fresh_proof(db, actor, payload)
    try:
        return await add_license_batch(
            db, store_id=product.store_id,
            product_id=product.id, codes=payload.codes,
        )
    except DeliveryPolicyError:
        raise security.SecurityRejected("invalid_digital_supply", 422) from None


@router.post("/products/{product_id}/digital-file")
async def upload_paid_file(
    product_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Stream one digitally sold file to the private, non-CDN storage root."""
    product = await _authorize_product(
        db, actor, request, product_id, write=True,
    )
    form = await request.form()
    uploaded = form.get("file")
    if not isinstance(uploaded, UploadFile) or not uploaded.filename:
        raise security.SecurityRejected("invalid_digital_file", 422)
    try:
        return await set_private_product_file(
            db, store_id=product.store_id, product_id=product.id,
            uploaded=uploaded,
        )
    except (DeliveryPolicyError, OSError, ValueError):
        raise security.SecurityRejected("invalid_digital_file", 422) from None


@router.get("/digital-deliveries")
async def list_digital_receipts(
    request: Request, actor: Actor, db: Db,
    status: str = "all",
) -> dict:
    """Inspect only non-secret, Store-owned digital delivery outcomes."""
    _, scope = require(actor, request, "orders.read")
    allowed = {"all", "queued", "sending", "delivered", "needs_review", "blocked"}
    if status not in allowed:
        raise security.SecurityRejected("invalid_digital_delivery_status", 422)
    query = select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.store_id.in_(scope.active_store_ids),
    )
    if status != "all":
        query = query.where(ShopDigitalDelivery.state == status)
    records = (await db.scalars(query.order_by(
        ShopDigitalDelivery.created_at.desc(),
        ShopDigitalDelivery.id,
    ).limit(100))).all()
    return {
        "items": [{
            "id": item.id, "store_id": item.store_id,
            "bot_id": item.bot_id, "order_id": item.order_id,
            "product_id": item.product_id,
            "kind": item.kind, "status": item.state,
            "provider_message_id": item.provider_message_id,
            "failure_code": item.failure_code,
            "claimed_at": item.claimed_at.isoformat()
                          if item.claimed_at else None,
            "delivered_at": item.delivered_at.isoformat()
                            if item.delivered_at else None,
        } for item in records],
        "automatic_retries": False,
    }
