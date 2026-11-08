"""Durable, one-time import authorization bound to staff, Store and session.

The receipt never stores the source CSV/XLSX or customer PII. A preview is
single-use and expires quickly. Row-level database state is fingerprinted so
an Apply after an intervening update must be previewed again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_model_import import ShopModelImportPreview
from services import shop_admin_security as security
from services.shop_store_context import StoreContext

PREVIEW_LIFETIME = timedelta(minutes=15)


async def issue_preview(
    db: AsyncSession, *, context: StoreContext,
    model_name: str, result: dict,
) -> dict:
    """Persist a short-lived proof after a successful read-only dry run."""
    now = datetime.now(timezone.utc)
    receipt = ShopModelImportPreview(
        id=str(uuid4()),
        staff_id=context.staff_id,
        session_id=context.session_id,
        store_id=context.current_store_id,
        store_context_version=context.version,
        dataset_name=model_name,
        file_sha256=result["sha256"],
        snapshot_sha256=result["snapshot_sha256"],
        rows=result["rows"],
        creates=result["creates"],
        updates=result["updates"],
        expires_at=now + PREVIEW_LIFETIME,
    )
    db.add(receipt)
    await db.commit()
    return {
        **result,
        "preview_id": receipt.id,
        "preview_expires_at": receipt.expires_at.isoformat(),
    }


async def claim_preview(
    db: AsyncSession, *, context: StoreContext, model_name: str,
    receipt_id: str, expected_sha256: str,
) -> ShopModelImportPreview:
    """Lock one proof, refusing stale, replayed or cross-Store application."""
    try:
        identifier = str(UUID(receipt_id))
    except (TypeError, ValueError):
        raise security.SecurityRejected("import_preview_required", 409) from None

    receipt = await db.scalar(select(ShopModelImportPreview).where(
        ShopModelImportPreview.id == identifier,
    ).with_for_update())
    if (
        receipt is None
        or receipt.staff_id != context.staff_id
        or receipt.session_id != context.session_id
        or receipt.store_id != context.current_store_id
        or receipt.store_context_version != context.version
        or receipt.dataset_name != model_name
        or receipt.file_sha256 != expected_sha256
        or receipt.consumed_at is not None
        or security.utc(receipt.expires_at) <= datetime.now(timezone.utc)
    ):
        raise security.SecurityRejected("import_preview_required", 409)
    context.require(receipt.store_id, write=True)
    return receipt
