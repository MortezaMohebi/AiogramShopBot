"""Exactly-once-attempt digital file/license delivery after paid settlement.

One durable delivery is reserved per OrderLine by the verified payment
transaction. The worker commits status=sending *before* a provider call.
Timeout, crash or absent provider message_id => needs_review, never an
automatic replay. An actual delivery is recorded only with the provider's
positive sent-message ID. The customer can inspect the receipt in Orders.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_checkout import ShopOrderLine
from models.shop_content import Product, ShopOrder
from models.shop_customer_support import (
    ShopFulfillmentEvent, ShopOrderFulfillment,
)
from models.shop_digital_delivery import (
    ShopDigitalAsset, ShopDigitalDelivery, ShopDigitalLicenseKey,
)
from models.shop_multibot import ShopBot, ShopStore
from models.shop_payment import ShopPaymentAttempt
from services.shop_digital_crypto import decrypt_license
from services.shop_digital_rules import (
    DeliveryPolicyError, allow_digital_delivery,
    validate_delivery_transition,
)
from services.shop_digital_storage import (
    private_license_document, verify_private_file,
)

LOGGER = logging.getLogger(__name__)


class PaidDocumentTransport(Protocol):
    """One native bot with an authenticated, non-retried sendDocument call."""

    async def send_private_document(
        self, chat_id: int, path, *, filename: str, caption: str,
    ) -> int:
        """Return the provider message ID only when confirmed as sent."""


async def claim_digital_delivery(
    db: AsyncSession, *, bot_id: str,
) -> ShopDigitalDelivery | None:
    """Atomically claim a verified paid-order delivery before remote I/O."""
    row = await db.scalar(select(ShopDigitalDelivery).join(
        ShopOrder, ShopOrder.id == ShopDigitalDelivery.order_id,
    ).join(
        ShopPaymentAttempt,
        ShopPaymentAttempt.order_id == ShopOrder.id,
    ).where(
        ShopDigitalDelivery.bot_id == bot_id,
        ShopDigitalDelivery.status == "queued",
        ShopOrder.bot_id == bot_id,
        ShopOrder.store_id == ShopDigitalDelivery.store_id,
        ShopOrder.status == "paid",
        ShopOrder.paid_at.is_not(None),
        ShopPaymentAttempt.bot_id == bot_id,
        ShopPaymentAttempt.status == "paid",
    ).order_by(ShopDigitalDelivery.id).limit(1).with_for_update(
        of=ShopDigitalDelivery, skip_locked=True,
    ))
    if row is None:
        return None
    validate_delivery_transition(row.status, "sending")
    row.status = "sending"
    row.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    return row


async def _read_delivery_payload(
    db: AsyncSession, row: ShopDigitalDelivery,
):
    """Recheck complete Store/Bot/order ownership and the private asset."""
    order = await db.get(ShopOrder, row.order_id)
    line = await db.get(ShopOrderLine, row.order_line_id)
    asset = await db.get(ShopDigitalAsset, row.asset_id)
    bot = await db.get(ShopBot, row.bot_id)
    store = await db.get(ShopStore, row.store_id)
    receipt = await db.scalar(select(ShopPaymentAttempt).where(
        ShopPaymentAttempt.order_id == row.order_id,
        ShopPaymentAttempt.bot_id == row.bot_id,
        ShopPaymentAttempt.status == "paid",
    ))
    product = await db.get(Product, line.product_id) if line else None
    correct_store = bool(
        order and line and asset and product and store
        and store.state == "active"
        and order.store_id == line.product.store_id
        if False else False
    )
    # Evaluate fields explicitly; a stale product or moved asset must never
    # cause a cross-Store attachment to be sent.
    correct_store = bool(
        order is not None and line is not None
        and asset is not None and product is not None
        and store is not None and store.state == "active"
        and order.store_id == row.store_id
        and product.store_id == row.store_id
        and asset.store_id == row.store_id
        and asset.product_id == line.product_id
        and line.order_id == row.order_id
        and line.quantity == row.quantity
    )
    correct_bot = bool(
        bot is not None and order is not None
        and bot.store_id == row.store_id
        and bot.platform == row.platform
        and order.bot_id == row.bot_id
        and order.platform == row.platform
        and order.platform_user_id == row.platform_user_id
        and order.chat_id == row.chat_id
        and (
            (bot.runtime_owner == "legacy" and bot.status == "legacy")
            or (bot.runtime_owner == "registry" and bot.status == "active")
        )
    )
    allow_digital_delivery(
        paid=bool(
            order is not None and order.status == "paid"
            and order.paid_at is not None and receipt is not None
        ),
        correct_store=correct_store,
        correct_bot=correct_bot,
        refunded=bool(
            order is not None and order.status == "refunded"
        ),
        asset_ready=bool(
            asset is not None and asset.kind in {"file", "license"}
        ),
    )
    if asset.kind == "file":
        if (
            not asset.storage_key
            or not asset.checksum_sha256
            or asset.checksum_sha256 != row.asset_sha256_snapshot
            or not asset.size_bytes
        ):
            raise DeliveryPolicyError("Paid asset version does not match Order.")
        path = verify_private_file(
            key=asset.storage_key, expected_size=asset.size_bytes,
            expected_sha256=asset.checksum_sha256,
        )
        return path, asset.original_filename or "paid-document", asset.kind

    codes = (await db.scalars(select(ShopDigitalLicenseKey).where(
        ShopDigitalLicenseKey.store_id == row.store_id,
        ShopDigitalLicenseKey.asset_id == asset.id,
        ShopDigitalLicenseKey.delivery_id == row.id,
        ShopDigitalLicenseKey.status == "reserved",
    ).order_by(ShopDigitalLicenseKey.id))).all()
    if len(codes) != row.quantity:
        raise DeliveryPolicyError("Reserved paid license set is incomplete.")
    return [
        decrypt_license(
            store_id=row.store_id, asset_id=asset.id,
            ciphertext=key.encrypted_code,
        ) for key in codes
    ], f"licenses-order-{row.order_id}.txt", asset.kind


async def finish_digital_delivery(
    db: AsyncSession, *, delivery_id: int,
    result: str, message_id: int | None = None,
) -> dict:
    """Commit a provider receipt or quarantine with no automatic retry."""
    if result not in {"delivered", "needs_review", "blocked"}:
        raise DeliveryPolicyError("Invalid digital delivery result.")
    record = await db.scalar(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.id == delivery_id,
    ).with_for_update())
    if record is None or record.status != "sending":
        raise DeliveryPolicyError("Delivery is missing or already finalized.")
    if result == "delivered" and (
        type(message_id) is not int or message_id <= 0
    ):
        raise DeliveryPolicyError("Provider message receipt is required.")
    validate_delivery_transition("sending", result)
    record.status = result
    if result == "delivered":
        record.provider_message_id = message_id
        record.delivered_at = datetime.now(timezone.utc)
        codes = (await db.scalars(select(ShopDigitalLicenseKey).where(
            ShopDigitalLicenseKey.delivery_id == record.id,
            ShopDigitalLicenseKey.status == "reserved",
        ).with_for_update())).all()
        for code in codes:
            code.status = "delivered"
        await db.flush()
        # Only a digital-only Order can be auto-marked fully delivered;
        # a mixed Bale Order retains its physical shipment lifecycle.
        all_lines = int(await db.scalar(select(func.count()).select_from(
            ShopOrderLine,
        ).where(ShopOrderLine.order_id == record.order_id)) or 0)
        delivered_lines = int(await db.scalar(select(func.count()).select_from(
            ShopDigitalDelivery,
        ).where(
            ShopDigitalDelivery.order_id == record.order_id,
            ShopDigitalDelivery.status == "delivered",
        )) or 0)
        if all_lines and all_lines == delivered_lines:
            shipment = await db.scalar(select(ShopOrderFulfillment).where(
                ShopOrderFulfillment.order_id == record.order_id,
                ShopOrderFulfillment.store_id == record.store_id,
            ).with_for_update())
            if shipment is None:
                shipment = ShopOrderFulfillment(
                    store_id=record.store_id,
                    order_id=record.order_id,
                    kind="digital", status="processing",
                )
                db.add(shipment)
                await db.flush()
            if shipment.kind == "digital" and shipment.status == "processing":
                shipment.status = "delivered"
                shipment.version += 1
                db.add(ShopFulfillmentEvent(
                    store_id=record.store_id,
                    fulfillment_id=shipment.id,
                    previous_status="processing",
                    next_status="delivered",
                    actor_id=None,
                    actor_kind="system",
                ))
    else:
        record.failure_code = (
            "provider_send_uncertain" if result == "needs_review"
            else "asset_or_owner_invalid"
        )
    await db.commit()
    return {
        "id": record.id, "status": record.status,
        "order_id": record.order_id,
        "provider_message_id": record.provider_message_id,
    }


async def deliver_one(
    db: AsyncSession, *, bot_id: str,
    transport: PaidDocumentTransport,
) -> bool:
    """Process one paid entitlement; provider is called at most once."""
    record = await claim_digital_delivery(db, bot_id=bot_id)
    if record is None:
        return False
    try:
        payload, filename, kind = await _read_delivery_payload(db, record)
    except (DeliveryPolicyError, OSError):
        await finish_digital_delivery(
            db, delivery_id=record.id, result="blocked",
        )
        return True
    try:
        caption = f"🔐 فایل دیجیتال سفارش #{record.order_id}"
        if kind == "license":
            with private_license_document(payload) as path:
                message_id = await transport.send_private_document(
                    record.chat_id, path, filename=filename,
                    caption=caption,
                )
        else:
            message_id = await transport.send_private_document(
                record.chat_id, payload, filename=filename,
                caption=caption,
            )
    except Exception:
        LOGGER.warning(
            "Digital provider delivery uncertain for receipt %s; "
            "requires manual review before any retry.",
            record.id,
        )
        await finish_digital_delivery(
            db, delivery_id=record.id, result="needs_review",
        )
        return True
    await finish_digital_delivery(
        db, delivery_id=record.id,
        result="delivered", message_id=message_id,
    )
    return True


async def quarantine_interrupted(
    db: AsyncSession, *, bot_id: str,
) -> int:
    """On worker restart, never automatically retry crashed sending rows."""
    rows = (await db.scalars(select(ShopDigitalDelivery).where(
        ShopDigitalDelivery.bot_id == bot_id,
        ShopDigitalDelivery.status == "sending",
    ).with_for_update(skip_locked=True).limit(100))).all()
    for item in rows:
        validate_delivery_transition("sending", "needs_review")
        item.status = "needs_review"
        item.failure_code = "worker_interrupted"
    await db.commit()
    return len(rows)
