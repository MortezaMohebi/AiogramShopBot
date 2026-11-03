"""Non-destructive Store and Bot Registry for the future multi-bot runtime.

The existing Telegram and Bale tables remain unchanged. Legacy bots are
represented by deterministic identifiers but continue using the legacy runtime
until a separately reviewed migration switches their dispatcher and payments.
"""

from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


# Fixed names allow a repeatable, idempotent reconciliation of legacy rows.
DEFAULT_STORE_ID = str(uuid5(NAMESPACE_URL, "aiogramshopbot:store:default:v1"))
LEGACY_TELEGRAM_BOT_ID = str(
    uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:telegram:v1")
)
LEGACY_BALE_BOT_ID = str(
    uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:bale:v1")
)
LEGACY_BOT_IDS = {
    "telegram": LEGACY_TELEGRAM_BOT_ID,
    "bale": LEGACY_BALE_BOT_ID,
}
ENV_TOKEN_KEYS = {"telegram": "TOKEN", "bale": "BALE_BOT_TOKEN"}


class ShopStore(Base):
    """One centrally managed shop, initially backed by the existing catalog."""

    __tablename__ = "shop_stores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "state IN ('active','paused','archived')",
            name="ck_shop_store_state",
        ),
    )


class ShopBot(Base):
    """Platform-specific bot registration independent of its API credential."""

    __tablename__ = "shop_bots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    store_id: Mapped[str] = mapped_column(
        ForeignKey("shop_stores.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(12), nullable=False)
    provider_bot_id: Mapped[int | None] = mapped_column(BigInteger)
    provider_username: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(18), nullable=False, default="draft", server_default="draft",
    )
    # A legacy bot is registered but NOT yet handled by the new dispatcher.
    runtime_owner: Mapped[str] = mapped_column(
        String(12), nullable=False, default="registry",
        server_default="registry",
    )
    credential_version: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("store_id", "slug", name="uq_shop_bots_store_slug"),
        UniqueConstraint(
            "platform", "provider_bot_id", name="uq_shop_bots_provider_identity",
        ),
        CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_bots_platform",
        ),
        CheckConstraint(
            "status IN ('draft','active','paused','maintenance','disabled','legacy')",
            name="ck_shop_bots_status",
        ),
        CheckConstraint(
            "runtime_owner IN ('legacy','registry')",
            name="ck_shop_bots_runtime_owner",
        ),
        CheckConstraint(
            "(runtime_owner != 'legacy' OR status = 'legacy') AND "
            "(status != 'legacy' OR runtime_owner = 'legacy')",
            name="ck_shop_bots_legacy_status",
        ),
        CheckConstraint("version > 0", name="ck_shop_bots_version"),
        CheckConstraint(
            "credential_version IS NULL OR credential_version > 0",
            name="ck_shop_bots_credential_version",
        ),
        Index("ix_shop_bots_store_status", "store_id", "status"),
    )


class ShopBotCredential(Base):
    """Versioned encrypted bot secret or a fixed, allowlisted environment ref."""

    __tablename__ = "shop_bot_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="staged",
        server_default="staged",
    )
    environment_key: Mapped[str | None] = mapped_column(String(40))
    ciphertext: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("bot_id", "version", name="uq_bot_credential_version"),
        CheckConstraint("version > 0", name="ck_bot_credential_version"),
        CheckConstraint(
            "source IN ('environment','encrypted')",
            name="ck_bot_credential_source",
        ),
        CheckConstraint(
            "state IN ('staged','active','revoked')",
            name="ck_bot_credential_state",
        ),
        CheckConstraint(
            "((source = 'environment' AND environment_key IN "
            "('TOKEN','BALE_BOT_TOKEN') AND ciphertext IS NULL) OR "
            "(source = 'encrypted' AND environment_key IS NULL AND "
            "ciphertext IS NOT NULL))",
            name="ck_bot_credential_material",
        ),
        Index("ix_bot_credentials_bot_state", "bot_id", "state"),
    )


class ShopBotRegistryEvent(Base):
    """Append-only registry audit without any secret or user-message content."""

    __tablename__ = "shop_bot_registry_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    bot_id: Mapped[str] = mapped_column(
        ForeignKey("shop_bots.id", ondelete="RESTRICT"), nullable=False,
        index=True,
    )
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("shop_staff.id", ondelete="SET NULL"),
    )
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    credential_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    __table_args__ = (
        CheckConstraint(
            "action IN ('legacy_adopted','bot_drafted','credential_staged',"
            "'credential_revoked','bot_updated')",
            name="ck_bot_registry_action",
        ),
    )


MULTIBOT_FOUNDATION_TABLES = frozenset({
    ShopStore.__tablename__,
    ShopBot.__tablename__,
    ShopBotCredential.__tablename__,
    ShopBotRegistryEvent.__tablename__,
})
