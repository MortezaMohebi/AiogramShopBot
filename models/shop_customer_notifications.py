"""Per-Bot operational/marketing notification Outbox and opt-in stock alerts.

An Outbox row is claimed durably before sending through a provider. A
transport timeout is unknown, not a safe retry. Alerts are per (Store, Bot,
user, product) and never inherit another Bot's advertising consent.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStockAlert(Base):
    """One customer's explicit product availability subscription per Bot."""

    __tablename__ = "shop_stock_alerts"

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
        nullable=False,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("shop_products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "bot_id", "platform_user_id", "product_id",
            name="uq_stock_alert_bot_user_product",
        ),
        CheckConstraint(
            "status IN ('active','queued','notified','cancelled')",
            name="ck_shop_stock_alert_status",
        ),
        Index("ix_stock_alert_store_status", "store_id", "status"),
    )


class ShopCustomerNotificationOutbox(Base):
    """Durably claimed provider message; uncertain sends require staff review."""

    __tablename__ = "shop_customer_notification_outbox"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
    )
    topic: Mapped[str] = mapped_column(String(16), nullable=False)
    event_key: Mapped[str] = mapped_column(
        String(120), nullable=False, unique=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "topic IN ('order','ticket','stock','marketing')",
            name="ck_shop_outbox_topic",
        ),
        CheckConstraint(
            "status IN ('queued','processing','sent','needs_review')",
            name="ck_shop_outbox_status",
        ),
        CheckConstraint(
            "length(body) BETWEEN 1 AND 4000",
            name="ck_shop_outbox_body",
        ),
        Index("ix_shop_outbox_store_status", "store_id", "status"),
    )


CUSTOMER_NOTIFICATION_TABLES = frozenset({
    ShopStockAlert.__tablename__,
    ShopCustomerNotificationOutbox.__tablename__,
})
