"""Registry-backed, many-to-many Telegram relay Worker topology.

Credentials are never readable in public/admin serialization. Multiple bots
may share a Worker, and one bot may have several ordered Workers. Outbound
authentication is bound to the individual (bot, worker, credential version).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class ShopRelayWorker(Base):
    """A single approved HTTPS Cloudflare relay deployment."""

    __tablename__ = "shop_relay_workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    origin: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft",
    )
    max_rps: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5",
    )
    max_inflight: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','paused','disabled')",
            name="ck_shop_relay_worker_status",
        ),
        CheckConstraint("max_rps BETWEEN 1 AND 20", name="ck_shop_relay_rps"),
        CheckConstraint(
            "max_inflight BETWEEN 1 AND 50", name="ck_shop_relay_inflight",
        ),
        CheckConstraint("version >= 1", name="ck_shop_relay_worker_version"),
    )


class ShopBotRelayRoute(Base):
    """A versioned, explicitly assigned route from one bot to one Worker."""

    __tablename__ = "shop_bot_relay_routes"

    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    worker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="staged",
        server_default="staged",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "bot_id", "priority", name="uq_bot_relay_route_priority",
        ),
        CheckConstraint(
            "status IN ('staged','active','paused')",
            name="ck_bot_relay_route_status",
        ),
        CheckConstraint(
            "priority BETWEEN 1 AND 1000", name="ck_bot_relay_priority",
        ),
        CheckConstraint("version >= 1", name="ck_bot_relay_version"),
        Index("ix_bot_relay_routes_worker", "worker_id", "status"),
    )


class ShopRelayCredential(Base):
    """A purpose-bound encrypted authenticator scoped to a bot/Worker pair."""

    __tablename__ = "shop_relay_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    worker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="staged",
        server_default="staged",
    )
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        UniqueConstraint(
            "bot_id", "worker_id", "version",
            name="uq_shop_relay_credential_version",
        ),
        CheckConstraint(
            "state IN ('staged','active','retiring','revoked')",
            name="ck_shop_relay_credential_state",
        ),
        CheckConstraint("version >= 1", name="ck_shop_relay_cred_version"),
        Index(
            "uq_shop_relay_nonrevoked_key", "key_fingerprint", unique=True,
            postgresql_where=text("state <> 'revoked'"),
        ),
        Index(
            "uq_shop_relay_active_credential",
            "bot_id", "worker_id", unique=True,
            postgresql_where=text("state = 'active'"),
        ),
    )


class ShopRelayEvent(Base):
    """Append-only operational receipts without token, endpoint or secret."""

    __tablename__ = "shop_relay_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    worker_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("shop_relay_workers.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    bot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("shop_bots.id", ondelete="RESTRICT"),
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


RELAY_POOL_TABLES = frozenset({
    ShopRelayWorker.__tablename__,
    ShopBotRelayRoute.__tablename__,
    ShopRelayCredential.__tablename__,
    ShopRelayEvent.__tablename__,
})
