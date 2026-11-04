"""Bot-owned stock subscriptions and durable notification consent/outbox.

Every delivery is explicitly associated with the provider-verified bot.
Marketing must have an active per-Bot opt-in; stock availability requires a
customer-initiated subscription. Failed/unknown send results never requeue
automatically, avoiding accidental duplicate provider messages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from channels.contracts import BotReply, InboundEvent, InlineAction
from models.shop_content import Product, ShopIdentity
from models.shop_customer_notifications import (
    ShopCustomerNotificationOutbox, ShopStockAlert,
)
from models.shop_multibot import ShopBot
from services.shop_bot_catalog_acl import allowed_for_bot
from services.shop_bot_context import BotContext
from services.shop_customer_account import customer_for_bot
from services.shop_customer_access import customer_access_allowed

_VALID_TOPICS = frozenset({"order", "ticket", "stock", "marketing"})
_EVENT_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_-]{6,119}\Z")
_STOCK_EVENT = re.compile(r"stock:([1-9][0-9]{0,18})(?::([0-9]{20}))?\Z")
_OUTBOX_TRANSITIONS = {
    "queued": frozenset({"processing", "cancelled"}),
    "processing": frozenset({"sent", "needs_review", "cancelled"}),
    "sent": frozenset(),
    "needs_review": frozenset(),
    "cancelled": frozenset(),
}


def _utc(value: datetime) -> datetime:
    """Normalize stored subscription timestamps without losing microseconds."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def stock_event_alert_id(event_key: str) -> int | None:
    """Read a bounded stock owner from legacy or generation-specific keys."""
    match = _STOCK_EVENT.fullmatch(event_key)
    if match is None:
        return None
    alert_id = int(match.group(1))
    return alert_id if alert_id <= 2**63 - 1 else None


def stock_event_matches(
    alert: ShopStockAlert, row: ShopCustomerNotificationOutbox,
) -> bool:
    """Bind a queued/send receipt to the current explicit subscription.

    First-generation keys retain their historical format. Later requests use
    the refreshed subscription timestamp as their durable generation, while
    old unversioned notices are valid only before a newer explicit request.
    """
    if stock_event_alert_id(row.event_key) != alert.id:
        return False
    base = f"stock:{alert.id}"
    if row.event_key == base:
        return bool(
            row.created_at is not None and alert.created_at is not None
            and _utc(row.created_at) >= _utc(alert.created_at)
        )
    generation = _utc(alert.created_at).strftime("%Y%m%d%H%M%S%f")
    return row.event_key == f"{base}:{generation}"


def notification_permitted(
    *, topic: str, advertising_consent: bool,
    explicit_request: bool,
) -> bool:
    """Require the right consent type for operational, stock or marketing."""
    if topic not in _VALID_TOPICS:
        return False
    if topic == "marketing":
        return advertising_consent is True
    if topic == "stock":
        return explicit_request is True
    return topic in {"order", "ticket"}


def can_deliver_at_dispatch(
    *, topic: str, advertising_consent: bool, explicit_request: bool,
    bot_active: bool, owner_valid: bool,
) -> bool:
    """Recheck LIVE owner, bot state, and topic-specific consent at send time."""
    return (
        bot_active is True
        and owner_valid is True
        and notification_permitted(
            topic=topic, advertising_consent=advertising_consent,
            explicit_request=explicit_request,
        )
    )


def validate_outbox_transition(current: str, new_status: str) -> bool:
    """Never reset an ambiguous, sent or processing provider message."""
    if new_status not in _OUTBOX_TRANSITIONS.get(current, frozenset()):
        raise ValueError("Unsafe notification state transition.")
    return True


async def toggle_stock_alert(
    db: AsyncSession, *, context: BotContext, user_id: int,
    product_id: int,
) -> BotReply:
    """Subscribe/unsubscribe by explicit customer action and current Bot ACL."""
    _, customer = await customer_for_bot(
        db, context, platform_user_id=user_id,
    )
    product = await db.get(Product, product_id)
    if product is None or product.store_id != context.store_id:
        return BotReply("این کالا به فروشگاه فعلی تعلق ندارد.")
    if not await allowed_for_bot(db, context.bot_id, [product_id]):
        return BotReply("این محصول در بات فعلی قابل‌نمایش نیست.")
    existing = await db.scalar(select(ShopStockAlert).where(
        ShopStockAlert.bot_id == context.bot_id,
        ShopStockAlert.platform_user_id == user_id,
        ShopStockAlert.product_id == product_id,
        ShopStockAlert.store_id == context.store_id,
    ).with_for_update())
    if existing is not None and existing.status in {"active", "queued"}:
        existing.status = "cancelled"
        response = "✅ درخواست اطلاع‌رسانی موجودی لغو شد."
    elif product.stock_quantity > 0:
        return BotReply(
            "این محصول هم‌اکنون موجود است؛ از صفحهٔ محصول خرید کنید.",
            ((InlineAction("📦 مشاهده محصول", f"shop:item:{product_id}"),),),
        )
    elif existing is not None:
        existing.status = "active"
        # A fresh customer request creates a distinct delivery authorization.
        # Keep timestamps monotonic even on a low-resolution system clock.
        existing.created_at = max(
            datetime.now(timezone.utc),
            _utc(existing.created_at) + timedelta(microseconds=1),
        )
        response = "✅ هنگام موجودشدن محصول از همین بات اطلاع‌رسانی می‌کنیم."
    else:
        db.add(ShopStockAlert(
            store_id=context.store_id, customer_id=customer.id,
            bot_id=context.bot_id, platform_user_id=user_id,
            product_id=product_id, status="active",
        ))
        response = "✅ اطلاع‌رسانی موجودشدن این محصول ثبت شد."
    await db.commit()
    return BotReply(
        response,
        ((InlineAction("📦 مشاهده محصول", f"shop:item:{product_id}"),),),
    )


async def list_stock_alerts(
    db: AsyncSession, *, context: BotContext, user_id: int,
) -> BotReply:
    """List only the authenticated Bot user's active stock alerts."""
    _, customer = await customer_for_bot(
        db, context, platform_user_id=user_id,
    )
    rows = (await db.execute(select(
        ShopStockAlert, Product.name,
    ).join(
        Product, Product.id == ShopStockAlert.product_id,
    ).where(
        ShopStockAlert.store_id == context.store_id,
        ShopStockAlert.customer_id == customer.id,
        ShopStockAlert.bot_id == context.bot_id,
        ShopStockAlert.platform_user_id == user_id,
        ShopStockAlert.status.in_(("active", "queued")),
    ).order_by(ShopStockAlert.id.desc()).limit(20))).all()
    buttons = tuple((
        InlineAction(
            f"🔕 لغو {name[:35]}", f"ux:stock:toggle:{alert.product_id}",
        ),
    ) for alert, name in rows)
    return BotReply(
        f"🔔 اعلان موجودی — {len(rows)} محصول",
        buttons + ((InlineAction("👤 حساب من", "ux:account"),),),
    )


async def enqueue_notification(
    db: AsyncSession, *, context: BotContext, user_id: int,
    topic: str, event_key: str, body: str, explicit_request: bool = False,
) -> bool:
    """Store one idempotent message only when consent/ownership are valid."""
    identity = await db.scalar(select(ShopIdentity).where(
        ShopIdentity.bot_id == context.bot_id,
        ShopIdentity.platform == context.platform.value,
        ShopIdentity.platform_user_id == user_id,
        ShopIdentity.store_id == context.store_id,
    ))
    if not await customer_access_allowed(db, identity):
        return False
    if (
        not isinstance(event_key, str) or not _EVENT_KEY.fullmatch(event_key)
        or not 1 <= len(body) <= 4000
        or not notification_permitted(
            topic=topic,
            advertising_consent=identity.allow_announcements,
            explicit_request=explicit_request,
        )
    ):
        return False
    exists = await db.scalar(select(
        ShopCustomerNotificationOutbox.id,
    ).where(
        ShopCustomerNotificationOutbox.event_key == event_key,
    ))
    if exists is not None:
        return False
    # A concurrent enqueue may win the event-key uniqueness race. Use a
    # SAVEPOINT so the duplicate does not roll back an atomic parent
    # transaction containing the staff reply or commerce state changes.
    try:
        async with db.begin_nested():
            db.add(ShopCustomerNotificationOutbox(
                store_id=context.store_id, bot_id=context.bot_id,
                platform_user_id=user_id,
                topic=topic, event_key=event_key,
                body=body, status="queued",
            ))
            await db.flush()
    except IntegrityError:
        return False
    return True


async def prepare_stock_alerts(
    db: AsyncSession, *, store_id: str, limit: int = 50,
) -> int:
    """Queue matching available Product alerts without sending messages."""
    if not 1 <= limit <= 100:
        raise ValueError("Invalid stock alert batch size.")
    records = (await db.scalars(select(ShopStockAlert).join(
        Product, Product.id == ShopStockAlert.product_id,
    ).join(
        ShopBot, ShopBot.id == ShopStockAlert.bot_id,
    ).where(
        ShopStockAlert.store_id == store_id,
        ShopStockAlert.status == "active",
        Product.store_id == store_id,
        Product.is_published.is_(True),
        Product.stock_quantity > 0,
        ShopBot.store_id == store_id,
        ShopBot.status.in_(("active", "legacy")),
    ).order_by(ShopStockAlert.id).limit(limit).with_for_update(
        skip_locked=True,
    ))).all()
    queued = 0
    for alert in records:
        bot = await db.get(ShopBot, alert.bot_id)
        from channels.contracts import Platform
        from services.shop_bot_context import BotContext

        context = BotContext(
            bot_id=bot.id, store_id=bot.store_id,
            platform=Platform(bot.platform),
            provider_bot_id=bot.provider_bot_id,
            status=bot.status, runtime_owner=bot.runtime_owner,
            credential_version=bot.credential_version,
            registry_version=bot.version,
        )
        if not await allowed_for_bot(db, context.bot_id, [alert.product_id]):
            continue
        product = await db.get(Product, alert.product_id)
        event_key = f"stock:{alert.id}"
        prior = await db.scalar(select(ShopCustomerNotificationOutbox.id).where(
            ShopCustomerNotificationOutbox.event_key == event_key,
        ))
        if prior is not None:
            generation = _utc(alert.created_at).strftime("%Y%m%d%H%M%S%f")
            event_key = f"{event_key}:{generation}"
        accepted = await enqueue_notification(
            db, context=context,
            user_id=alert.platform_user_id, topic="stock",
            event_key=event_key,
            body=f"📦 «{product.name[:180]}» دوباره موجود شده است.",
            explicit_request=True,
        )
        if accepted:
            alert.status = "queued"
            queued += 1
    await db.commit()
    return queued


async def claim_outbox_message(
    db: AsyncSession, *, bot_id: str, event_key: str | None = None,
) -> ShopCustomerNotificationOutbox | None:
    """Claim a queued message durably *before* its provider API request."""
    statement = select(ShopCustomerNotificationOutbox).where(
        ShopCustomerNotificationOutbox.bot_id == bot_id,
        ShopCustomerNotificationOutbox.status == "queued",
    )
    if event_key is not None:
        statement = statement.where(
            ShopCustomerNotificationOutbox.event_key == event_key,
        )
    row = await db.scalar(statement.order_by(
        ShopCustomerNotificationOutbox.id,
    ).with_for_update(skip_locked=True).limit(1))
    if row is None:
        return None
    validate_outbox_transition(row.status, "processing")
    row.status = "processing"
    row.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    return row


async def finish_outbox_message(
    db: AsyncSession, *, outbox_id: int, succeeded: bool,
    cancelled: bool = False,
) -> None:
    """Mark sent/unknown; never enqueue ambiguous outbound requests again."""
    row = await db.scalar(select(ShopCustomerNotificationOutbox).where(
        ShopCustomerNotificationOutbox.id == outbox_id,
    ).with_for_update())
    if row is None:
        raise ValueError("Outbox receipt is missing.")
    # A deterministic pre-send revocation differs from a network timeout.
    # A cancelled message was never sent and must not be retried either.
    next_status = (
        "cancelled" if cancelled else
        "sent" if succeeded else "needs_review"
    )
    validate_outbox_transition(row.status, next_status)
    row.status = next_status
    if succeeded:
        row.sent_at = datetime.now(timezone.utc)
    elif cancelled:
        row.failure_code = "authorization_revoked"
    else:
        row.failure_code = "provider_outcome_unknown"
    if row.topic == "stock" and row.event_key.startswith("stock:"):
        # Stock alerts are one-shot; once delivered or revoked, they must
        # never be resent due to a later inventory change.
        alert_id = stock_event_alert_id(row.event_key)
        alert = await db.scalar(select(ShopStockAlert).where(
            ShopStockAlert.id == alert_id,
        ).with_for_update().execution_options(
            populate_existing=True,
        )) if alert_id else None
        if (
            alert is not None and alert.bot_id == row.bot_id
            and alert.store_id == row.store_id
            and alert.platform_user_id == row.platform_user_id
            and alert.status == "queued"
            and stock_event_matches(alert, row)
        ):
            if succeeded:
                alert.status = "notified"
            elif cancelled:
                alert.status = "cancelled"
    await db.commit()
