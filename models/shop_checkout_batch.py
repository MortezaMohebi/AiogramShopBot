"""One customer-approved, two-currency checkout group for Telegram.

A mixed physical+digital Telegram cart is committed as two independent
ShopOrder records: the first uses fiat IRR, the second Stars XTR. Payment,
refund and fulfillment remain per Order, not shared or auto-transferred.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopCheckoutBatch(Base):
    """Immutable source-cart identity for exactly two checkout parts."""

    __tablename__ = "shop_checkout_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(
        String(12), nullable=False, default="telegram",
        server_default="telegram",
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
    )
    cart_id: Mapped[int] = mapped_column(
        ForeignKey("shop_carts.id", ondelete="RESTRICT"), nullable=False,
    )
    cart_revision: Mapped[int] = mapped_column(
        Integer, nullable=False,
    )
    quote_token: Mapped[str] = mapped_column(String(12), nullable=False)
    terms_version_snapshot: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "bot_id", "cart_id", "cart_revision",
            name="uq_shop_batch_bot_cart_revision",
        ),
        CheckConstraint(
            "platform = 'telegram'", name="ck_shop_batch_telegram_only",
        ),
        CheckConstraint(
            "cart_revision > 0", name="ck_shop_batch_revision",
        ),
        CheckConstraint(
            "length(quote_token) = 12", name="ck_shop_batch_quote_token",
        ),
    )


CHECKOUT_BATCH_TABLES = frozenset({ShopCheckoutBatch.__tablename__})
