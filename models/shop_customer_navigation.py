"""Declarative Store/Bot customer menus and bot-scoped chat form state.

These tables are part of the disposable Beta SQLAlchemy fresh schema.
They are not migrated from prior databases or shared between Providers.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStoreMenuPolicy(Base):
    """Default six-action menu visibility and order owned by a Store."""

    __tablename__ = "shop_store_menu_policies"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    actions_json: Mapped[str] = mapped_column(
        Text, nullable=False, default='["shop","search","cart","orders","account","support"]',
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_shop_store_menu_version"),
    )


class ShopBotMenuPolicy(Base):
    """Optional Bot-specific menu layout; never grants commerce entitlements."""

    __tablename__ = "shop_bot_menu_policies"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    actions_json: Mapped[str] = mapped_column(
        Text, nullable=False,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_shop_bot_menu_version"),
    )


class ShopCustomerChatState(Base):
    """Per-bot and per-provider-user FSM; no global chat state leakage."""

    __tablename__ = "shop_customer_chat_states"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    platform_user_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False, default="idle", server_default="idle",
    )
    query_text: Mapped[str | None] = mapped_column(String(100))
    page: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    __table_args__ = (
        CheckConstraint(
            "action IN ('idle','product_search','address_input','ticket_input')",
            name="ck_shop_chat_action",
        ),
        CheckConstraint("page BETWEEN 0 AND 10000", name="ck_shop_chat_page"),
        CheckConstraint("platform_user_id > 0", name="ck_shop_chat_user"),
    )


CUSTOMER_NAV_TABLES = frozenset({
    ShopStoreMenuPolicy.__tablename__,
    ShopBotMenuPolicy.__tablename__,
    ShopCustomerChatState.__tablename__,
})
