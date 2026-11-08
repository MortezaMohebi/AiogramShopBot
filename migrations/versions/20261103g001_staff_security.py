"""Add one-time staff invitations, recovery links and password policy.

Revision ID: 20261103g001
Revises: 20261103f001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261103g001"
down_revision: str | None = "20261103f001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add isolated security tables without changing existing staff passwords."""
    op.create_table(
        "shop_password_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("min_length", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("require_upper", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_lower", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_digit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("require_symbol", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_shop_password_policy_singleton"),
        sa.CheckConstraint("min_length BETWEEN 12 AND 64", name="ck_shop_password_policy_length"),
    )
    op.create_table(
        "shop_staff_invitations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("username", sa.String(80), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "role IN ('superadmin','sales','content','finance','marketing','viewer')",
            name="ck_staff_invitation_role",
        ),
    )
    op.create_index("ix_shop_staff_invitations_username", "shop_staff_invitations", ["username"])
    op.create_table(
        "shop_staff_password_resets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("shop_staff.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_shop_staff_password_resets_staff_id", "shop_staff_password_resets", ["staff_id"])


def downgrade() -> None:
    """Drop only the new security tables on an explicit rollback."""
    op.drop_index("ix_shop_staff_password_resets_staff_id", table_name="shop_staff_password_resets")
    op.drop_table("shop_staff_password_resets")
    op.drop_index("ix_shop_staff_invitations_username", table_name="shop_staff_invitations")
    op.drop_table("shop_staff_invitations")
    op.drop_table("shop_password_policy")
