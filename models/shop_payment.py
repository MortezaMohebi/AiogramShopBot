"""Payment attempts and refund cases shared by Telegram and Bale.

Financial records are append/transition-only. Administrators must not directly
edit provider identifiers, paid amounts, or payment state through SQLAdmin.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqladmin import ModelView

from models.base import Base
from models.shop_scope import legacy_bot_default
from models.shop_multibot import DEFAULT_STORE_ID


class ShopPaymentAttempt(Base):
    """One immutable currency/amount invoice intent for an approved order."""

    __tablename__ = "shop_payment_attempts"

    store_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_stores.id", ondelete="RESTRICT"),
        nullable=False, default=DEFAULT_STORE_ID, index=True,
    )
    payment_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_payment_accounts.id", ondelete="RESTRICT"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False, default=legacy_bot_default, index=True,
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="dispatching"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_shop_payment_positive"),
        CheckConstraint(
            "platform IN ('telegram','bale')",
            name="ck_shop_payment_platform",
        ),
        CheckConstraint(
            "provider IN ('bale_wallet','telegram_fiat','telegram_stars','store_credit')",
            name="ck_shop_payment_provider",
        ),
        CheckConstraint(
            "currency IN ('IRR','XTR')",
            name="ck_shop_payment_currency",
        ),
        CheckConstraint(
            "status IN ('dispatching','invoice_sent','dispatch_unknown',"
            "'paid','refunded')",
            name="ck_shop_payment_status",
        ),
    )


class ShopRefundCase(Base):
    """Auditable refund request; never implies an unverified bank transfer."""

    __tablename__ = "shop_refund_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("shop_orders.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="requested"
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','provider_pending','confirmed','rejected')",
            name="ck_shop_refund_case_status",
        ),
    )


class ShopPaymentAttemptAdmin(ModelView, model=ShopPaymentAttempt):
    """Read-only provider invoice ledger with no money-changing controls."""

    name = "تلاش پرداخت"
    name_plural = "تلاش‌های پرداخت"
    category = "مالی"
    icon = "fa-solid fa-credit-card"
    column_list = [
        ShopPaymentAttempt.order_id,
        ShopPaymentAttempt.platform,
        ShopPaymentAttempt.provider,
        ShopPaymentAttempt.currency,
        ShopPaymentAttempt.amount,
        ShopPaymentAttempt.status,
        ShopPaymentAttempt.created_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False


class ShopRefundCaseAdmin(ModelView, model=ShopRefundCase):
    """Track refund investigations; direct paid-state edits are forbidden."""

    name = "پرونده بازپرداخت"
    name_plural = "پرونده‌های بازپرداخت"
    category = "مالی"
    icon = "fa-solid fa-rotate-left"
    column_list = [
        ShopRefundCase.order_id,
        ShopRefundCase.status,
        ShopRefundCase.reason,
        ShopRefundCase.created_at,
        ShopRefundCase.resolved_at,
    ]
    can_create = False
    can_edit = False
    can_delete = False
    can_export = False
