"""Explicit Store/optional Bot checkout rules for a disposable Beta schema.

No payment is activated merely by enabling instant checkout. The native
Provider, Bot assignment, SKU stock, product type and consented sales terms
must all independently pass their own transaction-time checks.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStoreCheckoutPolicy(Base):
    """Store's default approval mode and customer-facing sales terms."""

    __tablename__ = "shop_store_checkout_policies"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    mode: Mapped[str] = mapped_column(
        String(12), nullable=False, default="manual", server_default="manual",
    )
    terms_version: Mapped[str] = mapped_column(
        String(32), nullable=False, default="v1", server_default="v1",
    )
    terms_text: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint(
            "mode IN ('manual','instant')", name="ck_store_checkout_mode",
        ),
        CheckConstraint(
            "length(terms_text) <= 6000", name="ck_store_checkout_terms_length",
        ),
        CheckConstraint(
            "length(terms_version) BETWEEN 1 AND 32",
            name="ck_store_checkout_terms_version",
        ),
        CheckConstraint("version > 0", name="ck_store_checkout_version"),
    )


class ShopBotCheckoutPolicy(Base):
    """Optional per-Bot approval mode override without currency bypass."""

    __tablename__ = "shop_bot_checkout_policies"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False,
    )
    mode_override: Mapped[str | None] = mapped_column(String(12))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint(
            "mode_override IS NULL OR mode_override IN ('manual','instant')",
            name="ck_bot_checkout_mode",
        ),
        CheckConstraint("version > 0", name="ck_bot_checkout_version"),
    )


CHECKOUT_POLICY_TABLES = frozenset({
    ShopStoreCheckoutPolicy.__tablename__,
    ShopBotCheckoutPolicy.__tablename__,
})
