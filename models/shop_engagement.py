"""Store-credit ledger, referrals and campaigns shared by Telegram and Bale.

Store credit belongs to this shop and remains independent of the customer's
native provider wallet balance.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base
from models.shop_multibot import DEFAULT_STORE_ID


class ShopWalletAccount(Base):
    """One nonnegative integer-IRR store-credit balance per platform identity."""

    __tablename__ = "shop_wallet_accounts"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("shop_store_customers.id", ondelete="RESTRICT"),
        index=True,
    )
    scope: Mapped[str] = mapped_column(
        String(12), nullable=False, default="identity",
        server_default="identity",
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=True, unique=True,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    balance_irr: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    identity: Mapped["ShopIdentity"] = relationship("ShopIdentity")

    __table_args__ = (
        CheckConstraint("balance_irr >= 0", name="ck_shop_wallet_balance"),
        CheckConstraint(
            "(scope = 'identity' AND identity_id IS NOT NULL "
            "AND bot_id IS NOT NULL) OR "
            "(scope = 'customer' AND identity_id IS NULL AND bot_id IS NULL)",
            name="ck_shop_wallet_scope",
        ),
        Index(
            "uq_shop_wallet_shared_customer", "store_id", "customer_id",
            unique=True, postgresql_where=text("scope = 'customer'"),
            sqlite_where=text("scope = 'customer'"),
        ),
    )


class ShopWalletEntry(Base):
    """Append-only signed credit/debit with a globally idempotent operation key."""

    __tablename__ = "shop_wallet_entries"

    source_identity_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("shop_wallet_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    operation_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    delta_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    account: Mapped[ShopWalletAccount] = relationship()

    __table_args__ = (
        CheckConstraint("delta_irr <> 0", name="ck_shop_wallet_entry_nonzero"),
        CheckConstraint(
            "balance_after_irr >= 0", name="ck_shop_wallet_entry_balance"
        ),
    )


class ShopReferralProfile(Base):
    """Optional referral code, scoped to an immutable shop identity."""

    __tablename__ = "shop_referral_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    code: Mapped[str] = mapped_column(
        String(24), nullable=False, unique=True
    )
    identity: Mapped["ShopIdentity"] = relationship("ShopIdentity")


class ShopReferralAttribution(Base):
    """One irreversible inviter attribution before first paid purchase."""

    __tablename__ = "shop_referral_attributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referee_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    inviter_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    code_snapshot: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "referee_identity_id != inviter_identity_id",
            name="ck_shop_referral_no_self",
        ),
    )


class ShopReferralPolicy(Base):
    """Explicitly enabled merchant-funded percentage of an IRR payment."""

    __tablename__ = "shop_referral_policy"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, default=1
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    min_order_irr: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    max_bonus_irr: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_shop_referral_policy_singleton"),
        CheckConstraint(
            "percent BETWEEN 0 AND 30", name="ck_shop_referral_percent"
        ),
        CheckConstraint(
            "min_order_irr >= 0", name="ck_shop_referral_minimum"
        ),
        CheckConstraint(
            "max_bonus_irr >= 0", name="ck_shop_referral_cap"
        ),
    )


class ShopReferralReward(Base):
    """Only one completed, provider-backed referral reward per new customer."""

    __tablename__ = "shop_referral_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referee_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    inviter_identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    bonus_irr: Mapped[int] = mapped_column(BigInteger, nullable=False)
    wallet_entry_id: Mapped[int] = mapped_column(
        ForeignKey("shop_wallet_entries.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("bonus_irr > 0", name="ck_shop_referral_bonus"),
    )


class ShopCampaign(Base):
    """Opt-in merchant campaign; no implicit automatic background scheduler."""

    __tablename__ = "shop_campaigns"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Legacy campaigns may address both platforms, so retain NULL for them.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audience: Mapped[str] = mapped_column(
        String(12), nullable=False, default="all"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    approved_by: Mapped[str | None] = mapped_column(String(120))
    # Frozen at start; external API calls may never exceed the approved cap.
    bale_mode: Mapped[str] = mapped_column(
        String(12), nullable=False, default="standard"
    )
    max_paid_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_calls_reserved: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "audience IN ('all','telegram','bale')",
            name="ck_shop_campaign_audience",
        ),
        CheckConstraint(
            "status IN ('draft','approved','sending','paused',"
            "'needs_review','completed','cancelled')",
            name="ck_shop_campaign_status",
        ),
        CheckConstraint(
            "bale_mode IN ('standard','business')", name="ck_shop_campaign_mode"
        ),
        CheckConstraint(
            "max_paid_calls >= 0 AND paid_calls_reserved >= 0 "
            "AND paid_calls_reserved <= max_paid_calls",
            name="ck_shop_campaign_budget",
        ),
    )


class ShopCampaignMedia(Base):
    """An optional, ordered attachment for a single draft campaign.

    The original file remains on private storage. A campaign may reference
    any number of attachments without a hardcoded product/file count.
    """

    __tablename__ = "shop_campaign_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("shop_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True
    )
    original_filename: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('photo','video','audio','document')",
            name="ck_shop_campaign_media_kind",
        ),
        CheckConstraint("size_bytes > 0", name="ck_shop_campaign_media_size"),
    )


class ShopCampaignDelivery(Base):
    """A single no-blind-retry send attempt for one opted-in recipient."""

    __tablename__ = "shop_campaign_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("shop_campaigns.id", ondelete="RESTRICT"),
        nullable=False,
    )
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Immutable Bot ownership comes from the authenticated runtime context.
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80))
    worker_id: Mapped[str | None] = mapped_column(String(48))

    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "identity_id", name="uq_shop_campaign_recipient"
        ),
        CheckConstraint(
            "status IN ('queued','sending','sent','unknown','skipped')",
            name="ck_shop_campaign_delivery_status",
        ),
        CheckConstraint("completed_steps >= 0", name="ck_shop_completed_steps"),
    )


class ShopBroadcastRateSlot(Base):
    """Durable global-bot and per-chat send pacing across worker processes."""

    __tablename__ = "shop_broadcast_rate_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Recipient ID zero reserves a global bot slot; positive IDs are chats.
    recipient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    next_send_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "platform", "bot_fingerprint", "recipient_id",
            name="uq_shop_broadcast_rate_slot",
        ),
        CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_broadcast_rate_platform",
        ),
        CheckConstraint(
            "recipient_id >= 0", name="ck_shop_broadcast_recipient_id"
        ),
    )


class ShopCampaignAudit(Base):
    """Append-only administrative and reconciliation lifecycle records."""

    __tablename__ = "shop_campaign_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("shop_campaigns.id", ondelete="RESTRICT"), nullable=False
    )
    delivery_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_campaign_deliveries.id", ondelete="RESTRICT")
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_status: Mapped[str] = mapped_column(String(24), nullable=False)
    new_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShopBroadcastWorkerHeartbeat(Base):
    """Heartbeat from a shared worker process for admin liveness reporting."""

    __tablename__ = "shop_broadcast_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(48), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
