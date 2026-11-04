"""Store-owned customers, configurable commerce policies and payment accounts.

Platform identities, native provider balances and legacy credit ledgers remain
independent until a verified customer link and an explicit financial cutover.
All new payment accounts are disabled by default and never expose credentials.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopStoreSettings(Base):
    """One optional brand/content configuration per nonlegacy Store."""

    __tablename__ = "shop_store_settings"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    brand_name: Mapped[str | None] = mapped_column(String(255))
    welcome_message: Mapped[str | None] = mapped_column(Text)
    faq_text: Mapped[str | None] = mapped_column(Text)
    support_url: Mapped[str | None] = mapped_column(String(500))


class ShopStoreCustomer(Base):
    """One verified merchant customer; provider user IDs are not primary keys."""

    __tablename__ = "shop_store_customers"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True, autoincrement=True,
    )
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    # Contact.user_id must match the provider-authenticated chat user.
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    external_ref: Mapped[str | None] = mapped_column(String(80))
    __table_args__ = (
        Index(
            "uq_shop_customer_store_external_ref",
            "store_id", "external_ref", unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
            sqlite_where=text("external_ref IS NOT NULL"),
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ShopStoreCustomerLinkEvent(Base):
    """Immutable proof that two bot identities were linked after both approved."""

    __tablename__ = "shop_store_customer_link_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_customer_link_requests.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    source_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"), nullable=False,
    )
    target_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"), nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class ShopStoreCommercePolicy(Base):
    """Explicit opt-in sharing; absent policy always isolates existing data."""

    __tablename__ = "shop_store_commerce_policies"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    cart_scope: Mapped[str] = mapped_column(
        String(12), nullable=False, default="bot", server_default="bot",
    )
    credit_scope: Mapped[str] = mapped_column(
        String(12), nullable=False, default="identity",
        server_default="identity",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint(
            "cart_scope IN ('bot','customer')",
            name="ck_store_commerce_cart_scope",
        ),
        CheckConstraint(
            "credit_scope IN ('identity','customer')",
            name="ck_store_commerce_credit_scope",
        ),
        CheckConstraint("version > 0", name="ck_store_commerce_version"),
    )


class ShopBotCommercePolicy(Base):
    """Optional per-bot feature overrides independent of the provider name."""

    __tablename__ = "shop_bot_commerce_policies"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    cart_enabled: Mapped[bool | None] = mapped_column(Boolean)
    credit_enabled: Mapped[bool | None] = mapped_column(Boolean)
    credit_label: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint(
            "credit_label IS NULL OR length(credit_label) BETWEEN 1 AND 80",
            name="ck_bot_commerce_credit_label",
        ),
        CheckConstraint("version > 0", name="ck_bot_commerce_version"),
    )


class ShopPaymentAccount(Base):
    """A store-owned external provider connection, not a customer balance."""

    __tablename__ = "shop_payment_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    rail_type: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft",
    )
    credential_ciphertext: Mapped[str | None] = mapped_column(Text)
    credential_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    __table_args__ = (
        CheckConstraint(
            "((platform = 'telegram' AND rail_type = 'telegram_stars' "
            "AND currency = 'XTR') OR "
            "(platform = 'telegram' AND rail_type = 'telegram_fiat' "
            "AND currency = 'IRR') OR "
            "(platform = 'bale' AND rail_type = 'bale_wallet' "
            "AND currency = 'IRR'))",
            name="ck_shop_payment_account_provider",
        ),
        CheckConstraint(
            "state IN ('draft','active','disabled')",
            name="ck_shop_payment_account_state",
        ),
        CheckConstraint("version > 0", name="ck_shop_payment_account_version"),
        CheckConstraint(
            "credential_version > 0", name="ck_shop_payment_secret_version",
        ),
        CheckConstraint(
            "(rail_type = 'telegram_stars' AND credential_ciphertext IS NULL) "
            "OR (rail_type != 'telegram_stars' AND "
            "credential_ciphertext IS NOT NULL)",
            name="ck_shop_payment_account_material",
        ),
    )


class ShopBotPaymentAccess(Base):
    """An explicit grant from a payment connection to one registered bot."""

    __tablename__ = "shop_bot_payment_access"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    payment_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_payment_accounts.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100",
    )
    __table_args__ = (
        CheckConstraint(
            "priority BETWEEN 1 AND 1000", name="ck_shop_payment_access_priority",
        ),
        Index("ix_shop_payment_access_account", "payment_account_id"),
    )


STORE_COMMERCE_TABLES = frozenset({
    ShopStoreSettings.__tablename__,
    ShopStoreCustomer.__tablename__,
    ShopStoreCommercePolicy.__tablename__,
    ShopStoreCustomerLinkEvent.__tablename__,
    ShopBotCommercePolicy.__tablename__,
    ShopPaymentAccount.__tablename__,
    ShopBotPaymentAccess.__tablename__,
})
