"""Additive, bot-scoped Many2many allow/deny product and category rules.

Registry bots default to deny. An absent rule is "inherit" and requires
no database row.
No product, order, wallet or historical customer column is replaced here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer,
    String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopBotProductRule(Base):
    """One explicit catalog entitlement for one bot/product pair."""

    __tablename__ = "shop_bot_product_rules"

    bot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shop_bots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shop_products.id", ondelete="CASCADE"),
        primary_key=True, index=True,
    )
    effect: Mapped[str] = mapped_column(String(5), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "effect IN ('allow','deny')", name="ck_bot_product_effect",
        ),
    )


class ShopBotCategoryRule(Base):
    """One explicit catalog entitlement for one bot/category pair."""

    __tablename__ = "shop_bot_category_rules"

    bot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("shop_bots.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shop_categories.id", ondelete="CASCADE"),
        primary_key=True, index=True,
    )
    effect: Mapped[str] = mapped_column(String(5), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "effect IN ('allow','deny')", name="ck_bot_category_effect",
        ),
    )


class ShopBotCatalogAudit(Base):
    """Append-only rule transition history; never store bot credentials."""

    __tablename__ = "shop_bot_catalog_audit"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4()),
    )
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    object_type: Mapped[str] = mapped_column(String(8), nullable=False)
    object_id: Mapped[int] = mapped_column(Integer, nullable=False)
    old_effect: Mapped[str] = mapped_column(String(7), nullable=False)
    new_effect: Mapped[str] = mapped_column(String(7), nullable=False)
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "object_type IN ('product','category')",
            name="ck_bot_acl_audit_object_type",
        ),
        CheckConstraint(
            "old_effect IN ('allow','deny','inherit')",
            name="ck_bot_acl_audit_old",
        ),
        CheckConstraint(
            "new_effect IN ('allow','deny','inherit')",
            name="ck_bot_acl_audit_new",
        ),
    )


BOT_CATALOG_ACL_TABLES = frozenset({
    ShopBotProductRule.__tablename__,
    ShopBotCategoryRule.__tablename__,
    ShopBotCatalogAudit.__tablename__,
})
