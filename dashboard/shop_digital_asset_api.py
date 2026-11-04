"""Signed admin management of private digital assets and mixed checkouts.

Only an authorized Store editor may upload encrypted digital merchandise.
Store-scoped responses NEVER include storage keys, license ciphertext, HMAC
fingerprints, absolute file paths, credentials or raw Provider payloads.
Management of a license pool requires recent administrator password/MFA
proof. Existing OrderLine asset snapshots remain immutable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from dashboard.admin_control_api import Proof, fresh_proof
from dashboard.next_api import database, signed_staff
from models.shop_checkout_batch import ShopCheckoutBatch
from models.shop_content import ShopOrder
from models.shop_digital_delivery import ShopDigitalDelivery
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_digital_assets as assets
from services.shop_digital_rules import DeliveryPolicyError
from services.shop_digital_storage import (
    private_file_path, store_digital_file,
)
from services.shop_store_context import StoreContext

router = APIRouter(
    prefix="/internal/admin/v1",
    tags=["Private digital merchandise"],
)
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


class LicenseMode(Proof):
    """Explicitly switch a Store Product into license-pool delivery mode."""

    confirmation: str = Field(
        min_length=20, max_length=30,
        pattern=r"^ACTIVATE_LICENSE_MODE$",
    )


class LicensePool(Proof):
    """Import valid encrypted codes without returning or logging their value."""

    codes: list[str] = Field(min_length=1, max_length=500)


def authorize(
    actor: ShopStaff | None, request: Request, *,
    permission: str, store_id: str | None = None,
    write: bool = False, manage: bool = False,
) -> StoreContext:
    """Require a signed active StoreContext, not a URL-selected tenant."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    security.require_permission(actor.role, permission)
    context = getattr(request.state, "store_context", None)
    if not isinstance(context, StoreContext):
        raise security.SecurityRejected("store_access_denied", 403)
    if store_id is not None:
        context.require(store_id, write=write, manage=manage)
    elif write:
        context.require(context.current_store_id, write=True)
    return context


@router.get("/digital-products/{product_id}/asset")
async def digital_product_asset(
    product_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Show non-secret delivery type, filename and free license-code counts."""
    context = authorize(actor, request, permission="catalog.read")
    if product_id <= 0:
        raise security.SecurityRejected("product_not_found", 404)
    return await assets.asset_snapshot(
        db, product_id=product_id,
        store_id=context.current_store_id,
    )


@router.post("/digital-products/{product_id}/file", status_code=201)
async def upload_digital_file(
    product_id: int, request: Request, actor: Actor, db: Db,
) -> dict:
    """Write one paid file to a non-public vault after permission validation.

    The signed middleware limits total request bytes; the private storage
    module enforces file byte limits independently and checks magic bytes.
    If the database rejects the new asset version, delete the newly written
    file while keeping the original paid Order asset untouched.
    """
    context = authorize(
        actor, request, permission="catalog.write", write=True,
    )
    if product_id <= 0:
        raise security.SecurityRejected("product_not_found", 404)
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;"):
        raise security.SecurityRejected("invalid_digital_file", 415)
    saved = None
    try:
        async with request.form(
            max_files=1, max_fields=3, max_part_size=8192,
        ) as form:
            uploaded = form.get("file")
            if not isinstance(uploaded, UploadFile) or not uploaded.filename:
                raise security.SecurityRejected("invalid_digital_file", 422)
            saved = await store_digital_file(uploaded)
        response = await assets.configure_file_asset(
            db, store_id=context.current_store_id,
            product_id=product_id, source=saved,
        )
        await db.commit()
        return response
    except (DeliveryPolicyError, OSError) as error:
        await db.rollback()
        raise security.SecurityRejected("digital_asset_not_ready", 409) from None
    except BaseException:
        await db.rollback()
        raise
    finally:
        if saved is not None:
            # A transaction may fail after the encrypted file is written;
            # never leave an unreferenced private asset in the vault.
            from models.shop_digital_delivery import ShopDigitalAsset

            stored = await db.scalar(select(ShopDigitalAsset.id).where(
                ShopDigitalAsset.storage_key == saved.storage_key,
                ShopDigitalAsset.store_id == context.current_store_id,
            ))
            if stored is None:
                private_file_path(saved.storage_key).unlink(missing_ok=True)


@router.post("/digital-products/{product_id}/license-mode")
async def switch_to_license_mode(
    product_id: int, payload: LicenseMode, request: Request,
    actor: Actor, db: Db,
) -> dict:
    """Switch file->license via fresh MFA and Store manager rights."""
    scope = authorize(
        actor, request, permission="catalog.write",
        write=True, manage=True,
    )
    await fresh_proof(db, actor, payload)
    try:
        return await assets.activate_license_mode(
            db, product_id=product_id,
            store_id=scope.current_store_id,
        )
    except DeliveryPolicyError:
        raise security.SecurityRejected(
            "digital_asset_change_blocked", 409,
        ) from None


@router.post("/digital-products/{product_id}/licenses")
async def add_license_codes(
    product_id: int, payload: LicensePool,
    request: Request, actor: Actor, db: Db,
) -> dict:
    """Consume an MFA-protected list once; return counts only, not codes."""
    scope = authorize(
        actor, request, permission="catalog.write",
        write=True, manage=True,
    )
    await fresh_proof(db, actor, payload)
    try:
        return await assets.import_license_pool(
            db, product_id=product_id, store_id=scope.current_store_id,
            codes=payload.codes,
        )
    except DeliveryPolicyError:
        raise security.SecurityRejected(
            "digital_license_import_denied", 409,
        ) from None


@router.get("/digital-deliveries")
async def digital_delivery_queue(
    request: Request, actor: Actor, db: Db,
) -> dict:
    """List bounded signed Provider receipts and statuses across active Stores."""
    scope = authorize(actor, request, permission="orders.read")
    records = (await db.scalars(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.store_id.in_(scope.active_store_ids),
    ).order_by(
        ShopDigitalDelivery.id.desc(),
    ).limit(100))).all()
    return {"items": [{
        "id": record.id, "store_id": record.store_id,
        "order_id": record.order_id,
        "bot_id": record.bot_id,
        "platform": record.platform,
        "asset_id": record.asset_id,
        "status": record.status,
        "provider_message_id": record.provider_message_id,
        "failure_code": record.failure_code,
        "delivered_at": (
            record.delivered_at.isoformat()
            if record.delivered_at else None
        ),
    } for record in records], "delivery_worker_opt_in": True}


@router.get("/checkout-batches/{batch_id}")
async def checkout_batch_detail(
    batch_id: UUID, request: Request, actor: Actor, db: Db,
) -> dict:
    """Show both independent child Orders without merging settlement state."""
    scope = authorize(actor, request, permission="orders.read")
    batch = await db.get(ShopCheckoutBatch, str(batch_id))
    if batch is None:
        raise security.SecurityRejected("checkout_batch_not_found", 404)
    scope.require(batch.store_id)
    children = (await db.scalars(select(ShopOrder).where(
        ShopOrder.checkout_batch_id == batch.id,
        ShopOrder.store_id == batch.store_id,
        ShopOrder.bot_id == batch.bot_id,
    ).order_by(ShopOrder.checkout_part))).all()
    return {
        "id": batch.id, "store_id": batch.store_id,
        "bot_id": batch.bot_id, "platform": batch.platform,
        "created_at": batch.created_at.isoformat(),
        "orders": [{
            "id": order.id, "part": order.checkout_part,
            "status": order.status, "provider": order.provider,
            "currency": order.payment_currency or (
                "XTR" if order.checkout_part == "digital" else "IRR"
            ),
            "amount_irr": str(order.total_irr),
            "amount_stars": order.total_stars_snapshot,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        } for order in children],
    }
