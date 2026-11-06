"""Verifiable Telegram↔Bale customer identity links with no data merger.

A link requires an action from each authenticated platform identity and a
final acknowledgement from the initiating identity. Tokens are stored hashed.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, String,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopCustomerLinkRequest(Base):
    """Short-lived, hashed three-step authorization for cross-provider linking."""

    __tablename__ = "shop_customer_link_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False,
    )
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_identities.id", ondelete="CASCADE"),
    )
    state: Mapped[str] = mapped_column(
        String(24), nullable=False, default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','awaiting_confirmation','confirmed','cancelled')",
            name="ck_customer_link_request_state",
        ),
    )


CUSTOMER_LINK_TABLES = frozenset({
    ShopCustomerLinkRequest.__tablename__,
})
