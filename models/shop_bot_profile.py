"""Persistent bot metadata independent of deployment credentials.

No bot API tokens, proxy passwords or private webhook URLs are stored here.
The provider identity is a verified stable ID, not a hash of the API token.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopBotProfile(Base):
    """Editable operator metadata and enforceable maintenance/receiver settings."""

    __tablename__ = "shop_bot_profiles"

    platform: Mapped[str] = mapped_column(String(12), primary_key=True)
    provider_bot_id: Mapped[int | None] = mapped_column(BigInteger)
    provider_username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(
        String(120), nullable=False, default="",
    )
    owner_staff_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    environment: Mapped[str] = mapped_column(
        String(16), nullable=False, default="staging", server_default="staging",
    )
    maintenance_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    request_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15, server_default="15",
    )
    poll_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10",
    )
    allowed_updates_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]",
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_bot_profile_platform",
        ),
        CheckConstraint(
            "environment IN ('codespaces','staging','production')",
            name="ck_bot_profile_environment",
        ),
        CheckConstraint(
            "request_timeout_seconds BETWEEN 5 AND 60",
            name="ck_bot_profile_request_timeout",
        ),
        CheckConstraint(
            "poll_timeout_seconds BETWEEN 0 AND 30",
            name="ck_bot_profile_poll_timeout",
        ),
    )


BOT_PROFILE_TABLES = frozenset({ShopBotProfile.__tablename__})
