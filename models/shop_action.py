"""Store-bound Action execution receipts and request-bound authorization proofs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopActionExecution(Base):
    """One atomic local execution or resumable pending authorization operation."""

    __tablename__ = "shop_action_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"), index=True
    )
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id", ondelete="RESTRICT"))
    platform: Mapped[str] = mapped_column(String(12))
    actor_key: Mapped[str] = mapped_column(String(64))
    action_key: Mapped[str] = mapped_column(String(81))
    action_version: Mapped[str] = mapped_column(String(32))
    idempotency_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    workflow_id: Mapped[str | None] = mapped_column(String(36))
    workflow_revision: Mapped[int | None] = mapped_column(Integer)
    workflow_run_id: Mapped[str | None] = mapped_column(String(36))
    node_id: Mapped[str | None] = mapped_column(String(64))
    side_effect: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24))
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    correlation_id: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "actor_key",
            "idempotency_sha256",
            name="uq_action_actor_idempotency",
        ),
        CheckConstraint("platform IN ('telegram','bale')", name="ck_action_platform"),
        CheckConstraint(
            "status IN ('succeeded','failed','retryable','pending_approval','pending_external','skipped','unavailable')",
            name="ck_action_status",
        ),
        CheckConstraint("retry_count >= 0", name="ck_action_retry_count"),
    )


class ShopActionAuthorization(Base):
    """Hashed proof for one actor, operation, payload, purpose and expiry window."""

    __tablename__ = "shop_action_authorizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"), index=True
    )
    bot_id: Mapped[str] = mapped_column(ForeignKey("shop_bots.id", ondelete="RESTRICT"))
    actor_key: Mapped[str] = mapped_column(String(64))
    action_key: Mapped[str] = mapped_column(String(81))
    action_version: Mapped[str] = mapped_column(String(32))
    invocation_id: Mapped[str] = mapped_column(String(36))
    input_sha256: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(24))
    issued_by: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_invocation_id: Mapped[str | None] = mapped_column(String(36))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('customer_confirmation','operator_approval')",
            name="ck_action_authorization_purpose",
        ),
        CheckConstraint(
            "expires_at > issued_at", name="ck_action_authorization_expiry"
        ),
    )
