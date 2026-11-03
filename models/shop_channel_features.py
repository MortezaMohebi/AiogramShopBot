"""Persistent, provider-scoped toggles for shared cart and store credit.

A missing row preserves the pre-existing enabled behavior for both Telegram
and Bale. Turning a feature off never deletes carts, balances or order history.
External Bale Wallet, Telegram Stars and other payment rails remain separate.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopChannelFeature(Base):
    """Merchant-controlled feature availability for one real bot provider."""

    __tablename__ = "shop_channel_features"

    platform: Mapped[str] = mapped_column(String(12), primary_key=True)
    cart_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    store_credit_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    store_credit_label: Mapped[str] = mapped_column(
        String(80), nullable=False, default="اعتبار فروشگاه",
        server_default="اعتبار فروشگاه",
    )
    changed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("platform IN ('telegram','bale')", name="ck_shop_feature_provider"),
        CheckConstraint(
            "length(store_credit_label) BETWEEN 1 AND 80",
            name="ck_shop_feature_credit_label",
        ),
    )


SHOP_CHANNEL_FEATURE_TABLES = frozenset({ShopChannelFeature.__tablename__})
