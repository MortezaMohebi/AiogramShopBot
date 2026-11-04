"""Store-scoped digital file/license inventory and guarded product setup.

Public ProductMedia is deliberately NOT used. A private asset can only be
downloaded by the digital-delivery worker after a verified payment. Signed
Admin calls show file metadata and license counts, never plaintext secrets.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

import config
from models.shop_content import Product
from models.shop_digital_delivery import ShopDigitalAsset, ShopDigitalLicense
from services.shop_digital_crypto import seal_license
from services.shop_digital_rules import DeliveryPolicyError
from services.shop_digital_storage import (
    digital_root, safe_digital_path, save_digital_file,
)


async def digital_catalog_snapshot(
    db: AsyncSession, *, store_id: str, product_id: int,
) -> dict:
    """Return only non-secret asset metadata for a Store-owned digital SKU."""
    product = await db.scalar(select(Product).where(
        Product.id == product_id, Product.store_id == store_id,
    ))
    if product is None:
        raise DeliveryPolicyError("Product is outside the current Store.")
    asset = await db.scalar(select(ShopDigitalAsset).where(
        ShopDigitalAsset.product_id == product_id,
        ShopDigitalAsset.store_id == store_id,
        ShopDigitalAsset.active.is_(True),
    ))
    available = int(await db.scalar(select(func.count()).select_from(
        ShopDigitalLicense,
    ).where(
        ShopDigitalLicense.product_id == product_id,
        ShopDigitalLicense.store_id == store_id,
        ShopDigitalLicense.state == "available",
    )) or 0)
    claimed = int(await db.scalar(select(func.count()).select_from(
        ShopDigitalLicense,
    ).where(
        ShopDigitalLicense.product_id == product_id,
        ShopDigitalLicense.store_id == store_id,
        ShopDigitalLicense.state != "available",
    )) or 0)
    return {
        "store_id": store_id, "product_id": product_id,
        "product_type": product.product_type,
        "mode": product.digital_delivery_mode,
        "stock_quantity": product.stock_quantity,
        "available_licenses": available,
        "claimed_or_delivered_licenses": claimed,
        "file": None if asset is None else {
            "id": asset.id,
            "original_filename": asset.original_filename,
            "size_bytes": asset.size_bytes,
            "sha256": asset.sha256,
            "mime_type": asset.mime_type,
        },
        "ready": (
            bool(asset) if product.digital_delivery_mode == "file"
            else available > 0 if product.digital_delivery_mode == "license"
            else False
        ),
    }


async def add_license_batch(
    db: AsyncSession, *, store_id: str, product_id: int,
    codes: list[str],
) -> dict:
    """Seal a bounded, unique batch and grow only *license-backed* stock."""
    if not isinstance(codes, list) or not 1 <= len(codes) <= 100:
        raise DeliveryPolicyError("Expected 1–100 one-time licenses.")
    product = await db.scalar(select(Product).where(
        Product.id == product_id,
        Product.store_id == store_id,
        Product.product_type == "digital",
    ).with_for_update())
    if product is None:
        raise DeliveryPolicyError("Not a Store-owned digital Product.")
    if product.digital_delivery_mode not in {"none", "license"}:
        raise DeliveryPolicyError(
            "Switching from private file to licenses requires a separate review."
        )
    prepared = [
        seal_license(store_id=store_id, product_id=product_id, code=code)
        for code in codes
    ]
    fingerprints = [fingerprint for _, fingerprint in prepared]
    if len(fingerprints) != len(set(fingerprints)):
        raise DeliveryPolicyError("Duplicate license code in the upload.")
    existing = await db.scalar(select(ShopDigitalLicense.id).where(
        ShopDigitalLicense.store_id == store_id,
        ShopDigitalLicense.product_id == product_id,
        ShopDigitalLicense.code_fingerprint.in_(fingerprints),
    ).limit(1))
    if existing is not None:
        raise DeliveryPolicyError("License was already imported.")

    # Prevent overselling: license-backed stock must match unclaimed codes.
    if product.digital_delivery_mode == "none":
        product.stock_quantity = 0
    if product.stock_quantity + len(prepared) > 100_000_000:
        raise DeliveryPolicyError("License inventory exceeds product limit.")
    for ciphertext, fingerprint in prepared:
        db.add(ShopDigitalLicense(
            id=str(uuid4()), store_id=store_id, product_id=product_id,
            ciphertext=ciphertext, code_fingerprint=fingerprint,
            state="available",
        ))
    product.stock_quantity += len(prepared)
    product.digital_delivery_mode = "license"
    await db.commit()
    return await digital_catalog_snapshot(
        db, store_id=store_id, product_id=product_id,
    )


async def set_private_product_file(
    db: AsyncSession, *, store_id: str, product_id: int,
    uploaded: UploadFile,
) -> dict:
    """Privately store an actual bounded file and activate a new asset version."""
    product = await db.scalar(select(Product).where(
        Product.id == product_id,
        Product.store_id == store_id,
        Product.product_type == "digital",
    ).with_for_update())
    if product is None:
        raise DeliveryPolicyError("Not a Store-owned digital Product.")
    if product.digital_delivery_mode not in {"none", "file"}:
        raise DeliveryPolicyError(
            "A license Product cannot silently switch to file delivery."
        )
    private = await save_digital_file(
        uploaded, root=config.SHOP_DIGITAL_ROOT,
        public_media_root=config.SHOP_MEDIA_ROOT,
        max_bytes=min(config.SHOP_MEDIA_MAX_BYTES, 50_000_000),
    )
    try:
        await db.execute(update(ShopDigitalAsset).where(
            ShopDigitalAsset.store_id == store_id,
            ShopDigitalAsset.product_id == product_id,
            ShopDigitalAsset.active.is_(True),
        ).values(active=False))
        db.add(ShopDigitalAsset(
            id=str(uuid4()), store_id=store_id,
            product_id=product_id,
            storage_key=private.storage_key,
            original_filename=private.original_filename,
            mime_type=private.mime_type,
            size_bytes=private.size_bytes, sha256=private.sha256,
            active=True,
        ))
        product.digital_delivery_mode = "file"
        await db.commit()
    except BaseException:
        await db.rollback()
        safe_digital_path(
            digital_root(
                config.SHOP_DIGITAL_ROOT,
                public_media_root=config.SHOP_MEDIA_ROOT,
            ),
            private.storage_key,
        ).unlink(missing_ok=True)
        raise
    return await digital_catalog_snapshot(
        db, store_id=store_id, product_id=product_id,
    )


async def require_digital_supply(
    db: AsyncSession, *, product: Product, quantity: int,
) -> ShopDigitalAsset | None:
    """Before invoice, ensure a paid Order can eventually be delivered.

    Settlement repeats the check under product/License row locks. An
    operator-deleted source must fail closed with a refund obligation.
    """
    if product.product_type != "digital":
        raise DeliveryPolicyError("Physical Product cannot use digital supply.")
    if type(quantity) is not int or quantity <= 0:
        raise DeliveryPolicyError("Invalid digital quantity.")
    if product.digital_delivery_mode == "file":
        asset = await db.scalar(select(ShopDigitalAsset).where(
            ShopDigitalAsset.product_id == product.id,
            ShopDigitalAsset.store_id == product.store_id,
            ShopDigitalAsset.active.is_(True),
        ))
        if asset is None:
            raise DeliveryPolicyError("Private digital file is not configured.")
        # File is never exposed through a static route. Validate current
        # path before accepting the Order, not only in the delivery worker.
        private = digital_root(
            config.SHOP_DIGITAL_ROOT,
            public_media_root=config.SHOP_MEDIA_ROOT,
        )
        path = safe_digital_path(private, asset.storage_key)
        if (
            not path.is_file() or path.is_symlink()
            or path.stat().st_size != asset.size_bytes
        ):
            raise DeliveryPolicyError("Private digital file is unavailable.")
        return asset
    if product.digital_delivery_mode == "license":
        available = int(await db.scalar(select(func.count()).select_from(
            ShopDigitalLicense,
        ).where(
            ShopDigitalLicense.store_id == product.store_id,
            ShopDigitalLicense.product_id == product.id,
            ShopDigitalLicense.state == "available",
        )) or 0)
        if available < quantity:
            raise DeliveryPolicyError(
                "Not enough unclaimed digital licenses available."
            )
        return None
    raise DeliveryPolicyError(
        "Digital Product has no private file or valid license inventory."
    )
