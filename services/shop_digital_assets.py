"""Store-owned digital asset configuration and paid-order entitlement staging.

An active file is a private checksum-pinned upload; a license asset uses
purpose-separated encrypted one-time codes. Availability is checked before
an invoice is issued and reservations are made atomically during a verified
successful-payment settlement, not on a precheckout acknowledgment.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_digital_delivery import (
    ShopDigitalAsset, ShopDigitalDelivery, ShopDigitalLicenseKey,
)
from services.shop_digital_crypto import encrypt_license
from services.shop_digital_rules import (
    DeliveryPolicyError, validate_license_code,
)
from services.shop_digital_storage import (
    MAX_DIGITAL_BYTES, PrivateDigitalFile, private_file_path,
)


async def active_asset(
    db: AsyncSession, *, store_id: str, product_id: int,
    lock: bool = False,
) -> ShopDigitalAsset | None:
    """Resolve only one currently approved Store-owned digital asset."""
    statement = select(ShopDigitalAsset).where(
        ShopDigitalAsset.store_id == store_id,
        ShopDigitalAsset.product_id == product_id,
        ShopDigitalAsset.is_active.is_(True),
    )
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def _asset_ready(
    db: AsyncSession, *, asset: ShopDigitalAsset, quantity: int,
) -> bool:
    """Check cheap, bounded prerequisites before an invoice is offered."""
    if not 1 <= quantity <= 99:
        return False
    if asset.kind == "file":
        if (
            not asset.storage_key or not asset.checksum_sha256
            or not asset.size_bytes
        ):
            return False
        try:
            file = private_file_path(asset.storage_key)
            return (
                file.is_file() and file.stat().st_size == asset.size_bytes
                and 0 < asset.size_bytes <= MAX_DIGITAL_BYTES
            )
        except (OSError, DeliveryPolicyError):
            return False
    if asset.kind == "license":
        count = await db.scalar(select(func.count()).select_from(
            ShopDigitalLicenseKey,
        ).where(
            ShopDigitalLicenseKey.asset_id == asset.id,
            ShopDigitalLicenseKey.store_id == asset.store_id,
            ShopDigitalLicenseKey.status == "available",
        ))
        return int(count or 0) >= quantity
    return False


async def require_digital_assets(
    db: AsyncSession, *, order_lines: list[tuple],
) -> dict[int, int]:
    """Refuse issuing a digital invoice without real files or enough codes."""
    selected: dict[int, int] = {}
    for line, product in order_lines:
        if product.product_type != "digital":
            continue
        snapshot_id = getattr(line, "digital_asset_id_snapshot", None)
        asset = (
            await db.get(ShopDigitalAsset, snapshot_id)
            if snapshot_id is not None
            else await active_asset(
                db, store_id=product.store_id, product_id=product.id,
            )
        )
        if (
            asset is None or asset.store_id != product.store_id
            or asset.product_id != product.id
            or not await _asset_ready(
                db, asset=asset, quantity=line.quantity,
            )
        ):
            raise DeliveryPolicyError(
                "Digital merchandise is not configured or out of license stock."
            )
        selected[product.id] = asset.id
    return selected


async def stage_digital_on_paid_receipt(
    db: AsyncSession, *, order: ShopOrder, order_lines: list[tuple],
) -> int:
    """Reserve licensed units and queue one delivery per paid OrderLine.

    This function must run within the verified provider settlement
    transaction, after matching its signed original Bot, charge, amount,
    currency and payer. The caller rolls back its SAVEPOINT if ANY digital
    line cannot be fulfilled; financial settlement still records
    paid_unfulfilled/refund obligation as required.
    """
    staged = 0
    for line, product in order_lines:
        if product.product_type != "digital":
            continue
        if (
            product.store_id != order.store_id or line.order_id != order.id
            or line.product_id != product.id
        ):
            raise DeliveryPolicyError("Cross-Store digital Order ownership.")
        # The price was accepted against this immutable Asset version.
        # Never deliver an admin-replaced file/license after payment.
        asset = (
            await db.get(
                ShopDigitalAsset, line.digital_asset_id_snapshot,
                with_for_update=True,
            )
            if line.digital_asset_id_snapshot is not None else None
        )
        if (
            asset is None or asset.store_id != order.store_id
            or asset.product_id != product.id
            or not await _asset_ready(
                db, asset=asset, quantity=line.quantity,
            )
        ):
            raise DeliveryPolicyError("Digital asset or licenses unavailable.")
        existing = await db.scalar(select(ShopDigitalDelivery.id).where(
            ShopDigitalDelivery.order_line_id == line.id,
        ))
        if existing is not None:
            raise DeliveryPolicyError("Digital delivery already reserved.")
        record = ShopDigitalDelivery(
            store_id=order.store_id, order_id=order.id,
            order_line_id=line.id, bot_id=order.bot_id,
            platform=order.platform, chat_id=order.chat_id,
            platform_user_id=order.platform_user_id,
            asset_id=asset.id,
            asset_sha256_snapshot=(
                asset.checksum_sha256 if asset.kind == "file" else None
            ),
            quantity=line.quantity, status="queued",
        )
        db.add(record)
        await db.flush()
        if asset.kind == "license":
            keys = (await db.scalars(select(ShopDigitalLicenseKey).where(
                ShopDigitalLicenseKey.store_id == order.store_id,
                ShopDigitalLicenseKey.asset_id == asset.id,
                ShopDigitalLicenseKey.status == "available",
            ).order_by(
                ShopDigitalLicenseKey.id,
            ).with_for_update(skip_locked=True).limit(line.quantity))).all()
            if len(keys) != line.quantity:
                raise DeliveryPolicyError("Not enough unassigned license codes.")
            for license_key in keys:
                license_key.status = "reserved"
                license_key.delivery_id = record.id
        staged += 1
    return staged


async def configure_file_asset(
    db: AsyncSession, *, product_id: int, store_id: str,
    source: PrivateDigitalFile,
) -> dict:
    """Install a new file version, preserving previous paid-order references."""
    product = await db.scalar(select(Product).where(
        Product.id == product_id,
        Product.store_id == store_id,
        Product.product_type == "digital",
    ).with_for_update())
    if product is None:
        raise DeliveryPolicyError("Target must be a digital Product in this Store.")
    previous = await active_asset(
        db, store_id=store_id, product_id=product_id, lock=True,
    )
    if previous is not None:
        previous.is_active = False
        await db.flush()
    asset = ShopDigitalAsset(
        store_id=store_id, product_id=product_id,
        kind="file", storage_key=source.storage_key,
        original_filename=source.name,
        mime_type=source.mime,
        size_bytes=source.size,
        checksum_sha256=source.sha256,
        is_active=True,
        version=(previous.version + 1 if previous else 1),
    )
    db.add(asset)
    await db.flush()
    return {
        "id": asset.id, "kind": asset.kind, "filename": source.name,
        "size_bytes": source.size, "version": asset.version,
    }


async def import_license_pool(
    db: AsyncSession, *, product_id: int, store_id: str,
    codes: list[str],
) -> dict:
    """Atomically import unique encrypted keys and synchronize sellable stock."""
    if not isinstance(codes, list) or not 1 <= len(codes) <= 500:
        raise DeliveryPolicyError("Import 1–500 valid license codes.")
    values = [validate_license_code(value) for value in codes]
    if len(values) != len(set(values)):
        raise DeliveryPolicyError("Duplicate license codes in input.")
    product = await db.scalar(select(Product).where(
        Product.id == product_id,
        Product.store_id == store_id,
        Product.product_type == "digital",
    ).with_for_update())
    if product is None:
        raise DeliveryPolicyError("Target must be a Store-owned digital Product.")
    asset = await active_asset(
        db, store_id=store_id, product_id=product_id, lock=True,
    )
    if asset is not None and asset.kind != "license":
        raise DeliveryPolicyError(
            "Switch the digital asset to license mode before importing codes."
        )
    if asset is None:
        last_version = int(await db.scalar(select(func.max(
            ShopDigitalAsset.version,
        )).where(
            ShopDigitalAsset.product_id == product_id,
            ShopDigitalAsset.store_id == store_id,
        )) or 0)
        asset = ShopDigitalAsset(
            store_id=store_id, product_id=product_id,
            kind="license", is_active=True, version=last_version + 1,
        )
        db.add(asset)
        await db.flush()
    encrypted = [
        encrypt_license(store_id=store_id, asset_id=asset.id, value=code)
        for code in values
    ]
    fingerprints = {fingerprint for _, fingerprint in encrypted}
    if len(fingerprints) != len(values):
        raise DeliveryPolicyError("Duplicate license fingerprints.")
    duplicates = await db.scalar(select(func.count()).select_from(
        ShopDigitalLicenseKey,
    ).where(
        ShopDigitalLicenseKey.store_id == store_id,
        ShopDigitalLicenseKey.code_fingerprint.in_(fingerprints),
    ))
    if duplicates:
        raise DeliveryPolicyError("One or more licenses already exist.")
    for ciphertext, fingerprint in encrypted:
        db.add(ShopDigitalLicenseKey(
            store_id=store_id, asset_id=asset.id,
            encrypted_code=ciphertext, code_fingerprint=fingerprint,
            status="available",
        ))
    # Stock is counted from unassigned keys. External Product stock edits
    # must be disabled while this asset kind is active.
    await db.flush()
    free = int(await db.scalar(select(func.count()).select_from(
        ShopDigitalLicenseKey,
    ).where(
        ShopDigitalLicenseKey.store_id == store_id,
        ShopDigitalLicenseKey.asset_id == asset.id,
        ShopDigitalLicenseKey.status == "available",
    )) or 0)
    product.stock_quantity = free
    await db.commit()
    return {
        "id": asset.id, "kind": "license",
        "imported": len(values), "available": free,
        "version": asset.version,
    }


async def asset_snapshot(
    db: AsyncSession, *, product_id: int, store_id: str,
) -> dict:
    """Return non-secret file metadata and key counts; never encrypted values."""
    product = await db.scalar(select(Product.id).where(
        Product.id == product_id, Product.store_id == store_id,
        Product.product_type == "digital",
    ))
    if product is None:
        raise DeliveryPolicyError("Digital Product not found in Store.")
    asset = await active_asset(
        db, store_id=store_id, product_id=product_id,
    )
    if asset is None:
        return {"product_id": product_id, "configured": False}
    counters = (await db.execute(select(
        ShopDigitalLicenseKey.status,
        func.count(ShopDigitalLicenseKey.id),
    ).where(
        ShopDigitalLicenseKey.store_id == store_id,
        ShopDigitalLicenseKey.asset_id == asset.id,
    ).group_by(
        ShopDigitalLicenseKey.status,
    ))).all()
    return {
        "product_id": product_id, "id": asset.id,
        "configured": True, "kind": asset.kind,
        "filename": asset.original_filename,
        "size_bytes": asset.size_bytes,
        "version": asset.version,
        "codes": {name: count for name, count in counters},
    }
