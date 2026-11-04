"""Paid-only, one-attempt Telegram/Bale private digital goods fulfillment.

Queue licenses/files within the exact provider successful_payment transaction.
A worker claims one row and commits its 'sending' receipt BEFORE a Bot API
request. Unknown outcomes stay needs_review; a process crash leaves sending
quarantined. Neither invoices nor precheckout updates deliver assets.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import config
from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_customer_support import (
    ShopFulfillmentEvent, ShopOrderFulfillment,
)
from models.shop_digital_delivery import (
    ShopDigitalAsset, ShopDigitalDelivery, ShopDigitalLicense,
)
from models.shop_multibot import ShopBot, ShopStore
from models.shop_payment import ShopPaymentAttempt
from services.shop_digital_catalog import require_digital_supply
from services.shop_digital_crypto import unseal_license
from services.shop_digital_rules import (
    DeliveryPolicyError, allow_digital_delivery,
    validate_delivery_transition, validate_pinned_asset,
)
from services.shop_digital_storage import digital_root, safe_digital_path


@dataclass(frozen=True, slots=True)
class DigitalSend:
    """Private provider send instruction, never returned to an HTTP client."""

    delivery_id: str
    bot_id: str
    chat_id: int
    kind: str
    caption: str
    asset_path: Path | None = None
    filename: str | None = None
    mime_type: str | None = None
    license_text: str | None = None


def _paid_in_ledger(order: ShopOrder, receipt: ShopPaymentAttempt | None) -> bool:
    """A precheckout/invoice-only record must never unlock paid content."""
    return bool(
        order.status == "paid"
        and order.paid_at is not None
        and receipt is not None and receipt.status == "paid"
        and receipt.order_id == order.id
        and receipt.bot_id == order.bot_id
        and receipt.store_id == order.store_id
        and receipt.provider == order.provider
    )


async def queue_paid_digital_order(
    db: AsyncSession, *, order: ShopOrder,
    pairs: list[tuple[ShopOrderLine, Product]],
) -> int:
    """Atomically reserve all paid units, or fail without partial delivery.

    Called only by ShopPaymentService.settle after proven Provider settlement
    and before the same transaction commits. Caller uses a SAVEPOINT: failure
    rolls back *all* claims and rows, and creates a RefundCase instead.
    """
    if (
        order.status != "paid"
        or not pairs
        or any(
            product.product_type != "digital"
            or product.store_id != order.store_id
            or line.order_id != order.id
            for line, product in pairs
        )
    ):
        raise DeliveryPolicyError("Expected one paid, digital-only Store Order.")

    created = 0
    for line, product in pairs:
        if type(line.quantity) is not int or line.quantity < 1:
            raise DeliveryPolicyError("Invalid digital OrderLine quantity.")
        if (
            product.digital_delivery_mode == "file"
            and not line.digital_asset_id_snapshot
        ):
            raise DeliveryPolicyError(
                "Purchased private file version was not saved."
            )
        asset = await require_digital_supply(
            db, product=product, quantity=line.quantity,
            pinned_asset_id=line.digital_asset_id_snapshot,
        )
        if product.digital_delivery_mode == "file":
            if asset is None:
                raise DeliveryPolicyError("Digital file not configured.")
            db.add(ShopDigitalDelivery(
                id=str(uuid4()), store_id=order.store_id,
                bot_id=order.bot_id, order_id=order.id,
                order_line_id=line.id, product_id=product.id,
                platform_user_id=order.platform_user_id,
                chat_id=order.chat_id, unit_index=0,
                kind="file", asset_id=asset.id, state="queued",
            ))
            created += 1
        elif product.digital_delivery_mode == "license":
            supply = (await db.scalars(select(ShopDigitalLicense).where(
                ShopDigitalLicense.store_id == order.store_id,
                ShopDigitalLicense.product_id == product.id,
                ShopDigitalLicense.state == "available",
            ).order_by(
                ShopDigitalLicense.id,
            ).with_for_update(skip_locked=True).limit(line.quantity))).all()
            if len(supply) != line.quantity:
                raise DeliveryPolicyError("Not enough one-time digital licenses.")
            for unit_index, item in enumerate(supply):
                item.state = "claimed"
                item.claimed_order_line_id = line.id
                item.claimed_unit_index = unit_index
                db.add(ShopDigitalDelivery(
                    id=str(uuid4()), store_id=order.store_id,
                    bot_id=order.bot_id, order_id=order.id,
                    order_line_id=line.id, product_id=product.id,
                    platform_user_id=order.platform_user_id,
                    chat_id=order.chat_id, unit_index=unit_index,
                    kind="license", license_id=item.id, state="queued",
                ))
                created += 1
        else:
            raise DeliveryPolicyError("Digital delivery is not configured.")

    from services.shop_fulfillment import ensure_fulfillment

    await db.flush()
    await ensure_fulfillment(db, order_id=order.id, store_id=order.store_id)
    return created


async def _preflight(
    db: AsyncSession, row: ShopDigitalDelivery,
) -> DigitalSend | None:
    """Check exact paid receipt, original Bot/Store and immutable asset key."""
    order = await db.get(ShopOrder, row.order_id)
    line = await db.get(ShopOrderLine, row.order_line_id)
    product = await db.get(Product, row.product_id)
    bot = await db.get(ShopBot, row.bot_id)
    store = await db.get(ShopStore, row.store_id)
    receipt = await db.scalar(select(ShopPaymentAttempt).where(
        ShopPaymentAttempt.order_id == row.order_id,
        ShopPaymentAttempt.bot_id == row.bot_id,
        ShopPaymentAttempt.store_id == row.store_id,
        ShopPaymentAttempt.status == "paid",
    ).limit(1))
    owner_valid = bool(
        order and line and product and bot and store
        and store.state == "active"
        and line.order_id == order.id
        and line.product_id == product.id
        and 0 <= row.unit_index < line.quantity
        and product.store_id == row.store_id
        and product.product_type == "digital"
        and order.store_id == row.store_id
        and order.bot_id == row.bot_id
        and order.platform_user_id == row.platform_user_id
        and order.chat_id == row.chat_id
        and bot.store_id == row.store_id
        and (
            bot.runtime_owner == "legacy" and bot.status == "legacy"
            or bot.runtime_owner == "registry" and bot.status == "active"
        )
    )
    paid = bool(order and _paid_in_ledger(order, receipt))
    if not owner_valid or not paid:
        return None
    if row.kind == "file":
        asset = await db.get(ShopDigitalAsset, row.asset_id)
        try:
            asset_ready = validate_pinned_asset(
                expected_asset_id=line.digital_asset_id_snapshot,
                actual_asset_id=asset.id if asset is not None else None,
                expected_store_id=row.store_id,
                actual_store_id=asset.store_id if asset is not None else "",
                expected_product_id=row.product_id,
                actual_product_id=asset.product_id if asset is not None else -1,
                asset_exists=asset is not None,
            )
        except DeliveryPolicyError:
            return None
        allow_digital_delivery(
            paid=paid, correct_store=owner_valid, correct_bot=owner_valid,
            asset_ready=asset_ready, refunded=False,
        )
        root = digital_root(
            config.SHOP_DIGITAL_ROOT,
            public_media_root=config.SHOP_MEDIA_ROOT,
        )
        path = safe_digital_path(root, asset.storage_key)
        if path.is_symlink() or not path.is_file() or (
            path.stat().st_size != asset.size_bytes
        ):
            raise DeliveryPolicyError("Private digital asset is missing.")
        # Stream hash from private storage to catch tampering on disk.
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != asset.sha256:
            raise DeliveryPolicyError("Private asset integrity check failed.")
        return DigitalSend(
            delivery_id=row.id, bot_id=row.bot_id, chat_id=row.chat_id,
            kind="file", caption="📥 فایل خریداری‌شدهٔ شما",
            asset_path=path,
            filename=asset.original_filename,
            mime_type=asset.mime_type,
        )

    if row.kind == "license":
        license_row = await db.get(ShopDigitalLicense, row.license_id)
        asset_ready = bool(
            license_row is not None
            and license_row.state == "claimed"
            and license_row.store_id == row.store_id
            and license_row.product_id == row.product_id
            and license_row.claimed_order_line_id == row.order_line_id
            and license_row.claimed_unit_index == row.unit_index
        )
        allow_digital_delivery(
            paid=paid, correct_store=owner_valid, correct_bot=owner_valid,
            asset_ready=asset_ready, refunded=False,
        )
        code = unseal_license(
            store_id=row.store_id, product_id=row.product_id,
            ciphertext=license_row.ciphertext,
        )
        return DigitalSend(
            delivery_id=row.id, bot_id=row.bot_id, chat_id=row.chat_id,
            kind="license", caption="🔐 کد لایسنس خریداری‌شدهٔ شما:",
            license_text=code,
        )
    return None


async def claim_one_delivery(
    db: AsyncSession, *, bot_id: str,
) -> DigitalSend | None:
    """Durably claim one verified paid item; blocked items never reach Provider."""
    delivery = await db.scalar(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.bot_id == bot_id,
        ShopDigitalDelivery.state == "queued",
    ).order_by(
        ShopDigitalDelivery.created_at, ShopDigitalDelivery.id,
    ).with_for_update(skip_locked=True).limit(1))
    if delivery is None:
        return None
    try:
        send = await _preflight(db, delivery)
    except (OSError, ValueError, DeliveryPolicyError):
        send = None
    if send is None:
        validate_delivery_transition(delivery.state, "blocked")
        delivery.state = "blocked"
        delivery.failure_code = "authorization_or_asset_unavailable"
        if delivery.license_id:
            license_row = await db.get(ShopDigitalLicense, delivery.license_id)
            if license_row is not None and license_row.state == "claimed":
                license_row.state = "needs_review"
        await db.commit()
        return None

    validate_delivery_transition(delivery.state, "sending")
    delivery.state = "sending"
    delivery.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    return send


async def complete_delivery(
    db: AsyncSession, *, delivery_id: str,
    provider_message_id: str | None,
) -> bool:
    """Persist confirmed provider Message ID and aggregate delivered status."""
    if (
        not isinstance(provider_message_id, str)
        or not re.fullmatch(r"[1-9][0-9]{0,78}", provider_message_id)
    ):
        raise DeliveryPolicyError("Provider did not confirm a message ID.")
    row = await db.scalar(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.id == delivery_id,
    ).with_for_update())
    if row is None or row.state != "sending":
        raise DeliveryPolicyError("Delivery claim is not active.")
    validate_delivery_transition(row.state, "delivered")
    row.state = "delivered"
    row.provider_message_id = provider_message_id
    row.delivered_at = datetime.now(timezone.utc)
    if row.license_id:
        license_row = await db.get(
            ShopDigitalLicense, row.license_id, with_for_update=True,
        )
        if license_row is None or license_row.state != "claimed":
            raise DeliveryPolicyError("Claimed license is inconsistent.")
        license_row.state = "delivered"
    await db.flush()
    remaining = int(await db.scalar(select(func.count()).select_from(
        ShopDigitalDelivery,
    ).where(
        ShopDigitalDelivery.order_id == row.order_id,
        ShopDigitalDelivery.store_id == row.store_id,
        ShopDigitalDelivery.state != "delivered",
    )) or 0)
    if remaining == 0:
        fulfillment = await db.scalar(select(ShopOrderFulfillment).where(
            ShopOrderFulfillment.order_id == row.order_id,
            ShopOrderFulfillment.store_id == row.store_id,
            ShopOrderFulfillment.kind == "digital",
        ).with_for_update())
        if fulfillment is None:
            raise DeliveryPolicyError("Digital Order fulfillment record is missing.")
        if fulfillment.status == "processing":
            fulfillment.status = "delivered"
            fulfillment.version += 1
            db.add(ShopFulfillmentEvent(
                store_id=row.store_id, fulfillment_id=fulfillment.id,
                previous_status="processing", next_status="delivered",
                actor_source="worker", actor_id=None,
            ))
    await db.commit()
    return True


async def quarantine_delivery(
    db: AsyncSession, *, delivery_id: str, failure_code: str,
) -> None:
    """An unknown result is never retried; preserve the claimed license."""
    row = await db.scalar(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.id == delivery_id,
    ).with_for_update())
    if row is None or row.state != "sending":
        raise DeliveryPolicyError("Delivery is no longer claimable.")
    validate_delivery_transition(row.state, "needs_review")
    row.state = "needs_review"
    row.failure_code = (
        failure_code if failure_code in {
            "provider_outcome_unknown", "invalid_message_receipt",
        } else "provider_outcome_unknown"
    )
    if row.license_id:
        license_row = await db.get(
            ShopDigitalLicense, row.license_id, with_for_update=True,
        )
        if license_row is not None and license_row.state == "claimed":
            license_row.state = "needs_review"
    await db.commit()
