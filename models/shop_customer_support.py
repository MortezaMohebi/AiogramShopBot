"""Store-owned support tickets, customer/staff messages and fulfillment events.

Ticket content and Shipment events are append-only. Each message belongs to
the same Store as its ticket; each fulfillment belongs to one immutable Order.
Financial state is owned by the payment service, never by these tables.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopSupportTicket(Base):
    """A customer-authenticated support case with one source Bot."""

    __tablename__ = "shop_support_tickets"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(16), nullable=False)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open",
    )
    assigned_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "topic IN ('general','order','payment','delivery','refund')",
            name="ck_shop_ticket_topic",
        ),
        CheckConstraint(
            "status IN ('open','pending','resolved','closed')",
            name="ck_shop_ticket_status",
        ),
        CheckConstraint("version > 0", name="ck_shop_ticket_version"),
        Index("ix_shop_ticket_store_status", "store_id", "status"),
    )


class ShopSupportMessage(Base):
    """One immutable message in a ticket, with unambiguous sender type."""

    __tablename__ = "shop_support_messages"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ticket_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_support_tickets.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    sender_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
    )
    staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"),
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "sender_kind IN ('customer','staff','system')",
            name="ck_shop_ticket_message_sender",
        ),
        CheckConstraint(
            "length(body) BETWEEN 1 AND 4000",
            name="ck_shop_ticket_message_body",
        ),
        CheckConstraint(
            "(sender_kind = 'customer' AND identity_id IS NOT NULL "
            "AND staff_id IS NULL) OR "
            "(sender_kind = 'staff' AND staff_id IS NOT NULL "
            "AND identity_id IS NULL) OR "
            "(sender_kind = 'system' AND staff_id IS NULL "
            "AND identity_id IS NULL)",
            name="ck_shop_ticket_message_actor",
        ),
    )


class ShopOrderFulfillment(Base):
    """One physical shipment or digital entitlement fulfillment per Order."""

    __tablename__ = "shop_order_fulfillments"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="processing",
        server_default="processing",
    )
    carrier: Mapped[str | None] = mapped_column(String(80))
    tracking_code: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "kind IN ('physical','digital')",
            name="ck_shop_fulfillment_kind",
        ),
        CheckConstraint(
            "status IN ('processing','ready','shipped','delivered')",
            name="ck_shop_fulfillment_status",
        ),
        CheckConstraint("version > 0", name="ck_shop_fulfillment_version"),
        CheckConstraint(
            "(kind = 'physical') OR (carrier IS NULL AND tracking_code IS NULL)",
            name="ck_shop_fulfillment_digital_no_carrier",
        ),
    )


class ShopFulfillmentEvent(Base):
    """Append-only fulfillment transition with staff provenance."""

    __tablename__ = "shop_fulfillment_events"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fulfillment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_order_fulfillments.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    next_status: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"), nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


SUPPORT_FULFILLMENT_TABLES = frozenset({
    ShopSupportTicket.__tablename__,
    ShopSupportMessage.__tablename__,
    ShopOrderFulfillment.__tablename__,
    ShopFulfillmentEvent.__tablename__,
})
