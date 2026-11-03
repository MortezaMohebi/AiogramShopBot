"""Create private customer CRM, consent provenance, and retention policy.

Revision ID: 20261103i001
Revises: 20261103h001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103i001"
down_revision: str | None = "20261103h001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add private profile and append-only support records without data loss."""
    op.create_table(
        "shop_customer_profiles",
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tags_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("owner_staff_id", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("support_status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("restriction_reason", sa.String(500)),
        sa.Column("restriction_until", sa.DateTime(timezone=True)),
        sa.Column("restricted_by", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.Column("restricted_at", sa.DateTime(timezone=True)),
        sa.Column("bot_blocked_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("support_status IN ('open','pending','resolved')", name="ck_customer_support_status"),
    )
    op.create_table(
        "shop_customer_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("length(content) BETWEEN 1 AND 4000", name="ck_customer_note_length"),
    )
    op.create_index("ix_shop_customer_notes_identity_id", "shop_customer_notes", ["identity_id"])
    op.create_table(
        "shop_customer_consent_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("topic", sa.String(60), nullable=False, server_default="shop_announcements"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('telegram_command','bale_command','customer_portal')", name="ck_customer_consent_source"),
    )
    op.create_index("ix_shop_customer_consent_events_identity_id", "shop_customer_consent_events", ["identity_id"])
    op.create_table(
        "shop_customer_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("identity_id", sa.Integer(), sa.ForeignKey("shop_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action IN ('profile_updated','note_added','restricted','restriction_cleared','data_exported')",
            name="ck_customer_audit_action",
        ),
    )
    op.create_index("ix_shop_customer_audit_identity_id", "shop_customer_audit", ["identity_id"])
    op.create_index("ix_customer_audit_actor_date", "shop_customer_audit", ["actor_id", "created_at"])
    op.create_table(
        "shop_customer_retention_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("note_retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("audit_retention_days", sa.Integer(), nullable=False, server_default="730"),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("shop_staff.id", ondelete="SET NULL")),
        sa.CheckConstraint("id = 1", name="ck_customer_retention_singleton"),
        sa.CheckConstraint("note_retention_days BETWEEN 30 AND 3650", name="ck_customer_note_retention"),
        sa.CheckConstraint("audit_retention_days BETWEEN 365 AND 3650", name="ck_customer_audit_retention"),
    )


def downgrade() -> None:
    """Delete only the new CRM tables on explicit and reviewed rollback."""
    op.drop_table("shop_customer_retention_policy")
    op.drop_index("ix_customer_audit_actor_date", table_name="shop_customer_audit")
    op.drop_index("ix_shop_customer_audit_identity_id", table_name="shop_customer_audit")
    op.drop_table("shop_customer_audit")
    op.drop_index("ix_shop_customer_consent_events_identity_id", table_name="shop_customer_consent_events")
    op.drop_table("shop_customer_consent_events")
    op.drop_index("ix_shop_customer_notes_identity_id", table_name="shop_customer_notes")
    op.drop_table("shop_customer_notes")
    op.drop_table("shop_customer_profiles")
