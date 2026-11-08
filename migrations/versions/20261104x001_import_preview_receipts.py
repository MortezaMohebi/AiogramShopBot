"""Add one-use, Store- and session-bound import preview receipts.

Revision ID: 20261104x001
Revises: 20261104w001

No existing Product, Customer, order or financial records are modified.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "20261104x001"
down_revision: str | None = "20261104w001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an immutable preview ledger used by the signed Import API."""
    op.create_table(
        "shop_model_import_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "staff_id", sa.Integer(),
            sa.ForeignKey("shop_staff.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id", sa.String(36),
            sa.ForeignKey("shop_admin_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "store_id", sa.String(36),
            sa.ForeignKey("shop_stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("store_context_version", sa.Integer(), nullable=False),
        sa.Column("dataset_name", sa.String(32), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("creates", sa.Integer(), nullable=False),
        sa.Column("updates", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "dataset_name IN ('products', 'customers')",
            name="ck_import_preview_dataset",
        ),
        sa.CheckConstraint(
            "rows BETWEEN 1 AND 1000 AND creates >= 0 AND updates >= 0",
            name="ck_import_preview_counts",
        ),
        sa.CheckConstraint(
            "store_context_version > 0",
            name="ck_import_preview_context_version",
        ),
        sa.CheckConstraint(
            "length(snapshot_sha256) = 64",
            name="ck_import_preview_snapshot_sha256",
        ),
        sa.CheckConstraint(
            "length(file_sha256) = 64",
            name="ck_import_preview_file_sha256",
        ),
    )
    op.create_index(
        "ix_import_previews_staff_session", "shop_model_import_previews",
        ["staff_id", "session_id", "expires_at"],
    )


def downgrade() -> None:
    """Preserve import authorization and consumption receipts for audit."""
    raise RuntimeError(
        "Import preview receipts must not be destructively downgraded."
    )
