"""Store-credit ledger, referrals and campaigns shared by Telegram and Bale.

Store credit belongs to this shop only. It is NOT the user's native Bale wallet
balance, nor can it be exchanged with the Telegram legacy crypto wallet.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqladmin import ModelView

from models.base import Base


class ShopWalletAccount(Base):
    """One nonnegative integer-IRR store-credit balance per platform identity."""

    __tablename__ = "shop_wallet_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identity_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="RESTRICT"),
        nullable=False, unique=True,
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
    )


class ShopWalletEntry(Base):
    """Append-only signed credit/debit with a globally idempotent operation key."""

    __tablename__ = "shop_wallet_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("shop_wallet_accounts.id", ondelete="RESTRICT"),
        nullable=False,
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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


class ShopWalletAccountAdmin(ModelView, model=ShopWalletAccount):
    """View balances; adjustments require audited finance tools."""

    name = "حساب اعتبار"
    name_plural = "موجودی اعتبار داخلی"
    category = "مالی"
    column_list = [
        ShopWalletAccount.identity_id, ShopWalletAccount.balance_irr,
        ShopWalletAccount.created_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False


class ShopWalletEntryAdmin(ModelView, model=ShopWalletEntry):
    """Inspect immutable credit, debit and referral entries."""

    name = "گردش اعتبار"
    name_plural = "دفترکل اعتبار"
    category = "مالی"
    column_list = [
        ShopWalletEntry.operation_key, ShopWalletEntry.account_id,
        ShopWalletEntry.delta_irr, ShopWalletEntry.balance_after_irr,
        ShopWalletEntry.reason, ShopWalletEntry.created_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class ShopReferralPolicyAdmin(ModelView, model=ShopReferralPolicy):
    """Only finance staff may enable merchant-funded referral rewards."""

    name = "سیاست معرفی"
    name_plural = "تنظیمات مالی معرفی مشتری"
    category = "مالی"
    form_columns = [
        ShopReferralPolicy.is_enabled, ShopReferralPolicy.percent,
        ShopReferralPolicy.min_order_irr, ShopReferralPolicy.max_bonus_irr,
    ]
    can_delete = False


class ShopReferralProfileAdmin(ModelView, model=ShopReferralProfile):
    """Read referral codes without exposing unrelated wallet credentials."""

    name = "کد معرفی"
    name_plural = "کدهای معرفی"
    category = "بازاریابی"
    column_list = [
        ShopReferralProfile.identity_id, ShopReferralProfile.code,
    ]
    can_create = False
    can_edit = False
    can_delete = False


class ShopReferralRewardAdmin(ModelView, model=ShopReferralReward):
    """View only fully recorded IRR rewards."""

    name = "پاداش معرفی"
    name_plural = "پاداش‌های معرفی"
    category = "بازاریابی"
    can_create = False
    can_edit = False
    can_delete = False


class ShopCampaignAdmin(ModelView, model=ShopCampaign):
    """Create an unsent draft; approval is performed in a separate CSRF view."""

    name = "کمپین"
    name_plural = "ارسال اطلاعیه به مشتریان"
    category = "بازاریابی"
    column_list = [
        ShopCampaign.id, ShopCampaign.title, ShopCampaign.audience,
        ShopCampaign.status, ShopCampaign.created_at,
    ]
    form_columns = [
        ShopCampaign.title, ShopCampaign.text, ShopCampaign.audience,
    ]
    can_create = True
    can_edit = False
    can_delete = False
    can_export = False


class ShopCampaignMediaAdmin(ModelView, model=ShopCampaignMedia):
    """Inspect uploaded attachments; only the guarded uploader may create."""

    name = "رسانه کمپین"
    name_plural = "فایل‌های کمپین‌های Broadcast"
    category = "بازاریابی"
    column_list = [
        ShopCampaignMedia.campaign_id, ShopCampaignMedia.original_filename,
        ShopCampaignMedia.kind, ShopCampaignMedia.size_bytes,
        ShopCampaignMedia.position,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class ShopCampaignDeliveryAdmin(ModelView, model=ShopCampaignDelivery):
    """Inspect delivery receipts without retry or deletion controls."""

    name = "رسید ارسال"
    name_plural = "وضعیت ارسال اطلاعیه‌ها"
    category = "بازاریابی"
    column_list = [
        ShopCampaignDelivery.campaign_id, ShopCampaignDelivery.identity_id,
        ShopCampaignDelivery.status, ShopCampaignDelivery.sent_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False

class ShopBroadcastRateSlot(Base):
    """Durable global-bot and per-chat send pacing across worker processes."""

    __tablename__ = "shop_broadcast_rate_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
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


class ShopCampaignAuditAdmin(ModelView, model=ShopCampaignAudit):
    """Show marketing decisions without permitting edits to the audit trail."""

    name = "سوابق کمپین"
    name_plural = "سوابق مدیریت Broadcast"
    category = "بازاریابی"
    column_list = [
        ShopCampaignAudit.campaign_id, ShopCampaignAudit.delivery_id,
        ShopCampaignAudit.actor, ShopCampaignAudit.action,
        ShopCampaignAudit.previous_status, ShopCampaignAudit.new_status,
        ShopCampaignAudit.created_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class ShopBroadcastRateSlotAdmin(ModelView, model=ShopBroadcastRateSlot):
    """Inspect global/per-recipient rate reservations as read-only metadata."""

    name = "سهمیه ارسال"
    name_plural = "کنترل نرخ ارسال"
    category = "بازاریابی"
    column_list = [
        ShopBroadcastRateSlot.platform,
        ShopBroadcastRateSlot.recipient_id,
        ShopBroadcastRateSlot.next_send_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
