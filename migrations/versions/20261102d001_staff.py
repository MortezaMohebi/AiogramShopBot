"""Introduce revocable, role-based SQLAdmin staff accounts.

Revision ID: 20261102d001
Revises: 20261102c001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261102d001"
down_revision: Union[str, None] = "20261102c001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the staff table without provisioning default credentials."""
    op.create_table(
        "shop_staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(80), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role", sa.String(20), nullable=False,
            server_default="viewer",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "session_version", sa.Integer(), nullable=False,
            server_default="1",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('superadmin','sales','content','finance','marketing','viewer')",
            name="ck_shop_staff_role",
        ),
        sa.CheckConstraint(
            "session_version > 0", name="ck_shop_staff_session_version"
        ),
    )


def downgrade() -> None:
    """Drop staff accounts only when explicitly rolling back the migration."""
    op.drop_table("shop_staff")
