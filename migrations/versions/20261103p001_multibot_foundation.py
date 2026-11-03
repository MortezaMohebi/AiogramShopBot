"""Add Store/Bot/Credential Registry without modifying any legacy business table.

Revision ID: 20261103p001
Revises: 20261103o001

Upgrade creates four tables and adopts the two currently configured legacy
bot identities. It never moves/deletes existing carts, orders, wallet ledgers,
inbound receipts, bot profiles, or Telegram transport settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid4, uuid5

from alembic import op
import sqlalchemy as sa

revision: str = "20261103p001"
down_revision: str | None = "20261103o001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STORE_ID = str(uuid5(NAMESPACE_URL, "aiogramshopbot:store:default:v1"))
_BOT_IDS = {
    "telegram": str(uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:telegram:v1")),
    "bale": str(uuid5(NAMESPACE_URL, "aiogramshopbot:bot:legacy:bale:v1")),
}
_ENV_KEYS = {"telegram": "TOKEN", "bale": "BALE_BOT_TOKEN"}


def upgrade() -> None:
    """Add metadata and safely associate existing Telegram and Bale profiles."""
    op.create_table(
        "shop_stores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "state IN ('active','paused','archived')", name="ck_shop_store_state",
        ),
    )
    op.create_table(
        "shop_bots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("platform", sa.String(12), nullable=False),
        sa.Column("provider_bot_id", sa.BigInteger()),
        sa.Column("provider_username", sa.String(255)),
        sa.Column("status", sa.String(18), nullable=False, server_default="draft"),
        sa.Column(
            "runtime_owner", sa.String(12), nullable=False,
            server_default="registry",
        ),
        sa.Column("credential_version", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("store_id", "slug", name="uq_shop_bots_store_slug"),
        sa.UniqueConstraint(
            "platform", "provider_bot_id",
            name="uq_shop_bots_provider_identity",
        ),
        sa.CheckConstraint(
            "platform IN ('telegram','bale')", name="ck_shop_bots_platform",
        ),
        sa.CheckConstraint(
            "status IN ('draft','active','paused','maintenance','disabled','legacy')",
            name="ck_shop_bots_status",
        ),
        sa.CheckConstraint(
            "runtime_owner IN ('legacy','registry')",
            name="ck_shop_bots_runtime_owner",
        ),
        sa.CheckConstraint(
            "(runtime_owner != 'legacy' OR status = 'legacy') AND "
            "(status != 'legacy' OR runtime_owner = 'legacy')",
            name="ck_shop_bots_legacy_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_shop_bots_version"),
        sa.CheckConstraint(
            "credential_version IS NULL OR credential_version > 0",
            name="ck_shop_bots_credential_version",
        ),
    )
    op.create_index("ix_shop_bots_store_id", "shop_bots", ["store_id"])
    op.create_index(
        "ix_shop_bots_store_status", "shop_bots", ["store_id", "status"],
    )
    op.create_table(
        "shop_bot_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="staged"),
        sa.Column("environment_key", sa.String(40)),
        sa.Column("ciphertext", sa.Text()),
        sa.Column(
            "created_by", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "bot_id", "version", name="uq_bot_credential_version",
        ),
        sa.CheckConstraint("version > 0", name="ck_bot_credential_version"),
        sa.CheckConstraint(
            "source IN ('environment','encrypted')",
            name="ck_bot_credential_source",
        ),
        sa.CheckConstraint(
            "state IN ('staged','active','revoked')",
            name="ck_bot_credential_state",
        ),
        sa.CheckConstraint(
            "((source = 'environment' AND environment_key IN "
            "('TOKEN','BALE_BOT_TOKEN') AND ciphertext IS NULL) OR "
            "(source = 'encrypted' AND environment_key IS NULL AND "
            "ciphertext IS NOT NULL))",
            name="ck_bot_credential_material",
        ),
    )
    op.create_index(
        "ix_shop_bot_credentials_bot_id", "shop_bot_credentials", ["bot_id"],
    )
    op.create_index(
        "ix_bot_credentials_bot_state", "shop_bot_credentials",
        ["bot_id", "state"],
    )
    # PostgreSQL ensures no two credentials can simultaneously be active.
    op.create_index(
        "uq_bot_credential_one_active", "shop_bot_credentials",
        ["bot_id"], unique=True,
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "shop_bot_registry_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id", sa.String(36),
            sa.ForeignKey("shop_bots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="SET NULL"),
        ),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("credential_version", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "action IN ('legacy_adopted','bot_drafted','credential_staged',"
            "'credential_revoked','bot_updated')",
            name="ck_bot_registry_action",
        ),
    )
    op.create_index(
        "ix_shop_bot_registry_events_bot_id",
        "shop_bot_registry_events", ["bot_id"],
    )

    _adopt_legacy_without_touching_business_data()


def _adopt_legacy_without_touching_business_data() -> None:
    """Register each original platform once, using historical profile metadata."""
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT platform, provider_bot_id, provider_username, "
        "display_name, verified_at FROM shop_bot_profiles "
        "WHERE platform IN ('telegram', 'bale')"
    )).mappings().all()
    profiles = {row["platform"]: row for row in rows}
    shop_name = conn.scalar(sa.text(
        "SELECT NULLIF(TRIM(brand_name), '') FROM shop_settings "
        "WHERE id = 1"
    )) or "فروشگاه اصلی"

    conn.execute(sa.text(
        "INSERT INTO shop_stores (id, slug, name, state) "
        "VALUES (:id, 'default', :name, 'active')"
    ), {"id": _STORE_ID, "name": str(shop_name)[:160]})

    for platform, bot_id in _BOT_IDS.items():
        profile = profiles.get(platform, {})
        conn.execute(sa.text(
            "INSERT INTO shop_bots "
            "(id, store_id, slug, name, platform, provider_bot_id, "
            "provider_username, status, runtime_owner, credential_version, "
            "version, verified_at) "
            "VALUES (:id, :store_id, :slug, :name, :platform, :provider_id, "
            ":username, 'legacy', 'legacy', 1, 1, :verified_at)"
        ), {
            "id": bot_id,
            "store_id": _STORE_ID,
            "slug": f"legacy-{platform}",
            "name": (
                str(profile.get("display_name") or f"Legacy {platform} Bot")
            )[:160],
            "platform": platform,
            "provider_id": profile.get("provider_bot_id"),
            "username": profile.get("provider_username"),
            "verified_at": profile.get("verified_at"),
        })
        conn.execute(sa.text(
            "INSERT INTO shop_bot_credentials "
            "(id, bot_id, version, source, state, environment_key) "
            "VALUES (:id, :bot_id, 1, 'environment', 'active', :env_key)"
        ), {
            "id": str(uuid4()),
            "bot_id": bot_id,
            "env_key": _ENV_KEYS[platform],
        })
        conn.execute(sa.text(
            "INSERT INTO shop_bot_registry_events "
            "(id, bot_id, action, credential_version) "
            "VALUES (:id, :bot_id, 'legacy_adopted', 1)"
        ), {"id": str(uuid4()), "bot_id": bot_id})


def downgrade() -> None:
    """Refuse destructive rollback: this migration only adds registry data."""
    raise RuntimeError(
        "Refusing to drop the multi-bot registry. Preserve credentials "
        "and legacy mappings; use a reviewed data-preserving downgrade."
    )
