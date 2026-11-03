"""Merchant-configurable payment method names and activation flags.

Only documented provider rails are allowed. Credentials remain in deployment
secrets; arbitrary payment handlers cannot be registered from the dashboard.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String,
    UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopPaymentRail(Base):
    """One supported payment integration per messaging platform."""

    __tablename__ = "shop_payment_rails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    rail_type: Mapped[str] = mapped_column(String(24), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        UniqueConstraint("platform", "rail_type", name="uq_shop_payment_rail"),
        CheckConstraint(
            "(platform = 'telegram' AND rail_type IN "
            "('store_credit','telegram_fiat','telegram_stars')) OR "
            "(platform = 'bale' AND rail_type IN "
            "('store_credit','bale_wallet'))",
            name="ck_shop_payment_rail_supported",
        ),
        CheckConstraint(
            "length(display_name) BETWEEN 1 AND 80",
            name="ck_shop_payment_rail_label",
        ),
    )


PAYMENT_RAIL_TABLES = frozenset({ShopPaymentRail.__tablename__})
