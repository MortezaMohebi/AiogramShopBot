"""Create editable shop content tables without altering legacy purchase data.

Revision ID: 20261102a001
Revises: 91c3856a8aa0
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261102a001"
down_revision: Union[str, None] = "91c3856a8aa0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the new catalog, media, and testimonial tables."""
    op.create_table(
        "shop_products",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("sku", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
        sa.Column("stock_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("price >= 0", name="ck_shop_product_price"),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_shop_product_stock"),
    )
    op.create_table(
        "shop_product_media",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("caption", sa.Text),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_published", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("kind IN ('photo', 'video', 'audio', 'document')", name="ck_shop_media_kind"),
    )
    op.create_table(
        "shop_testimonials",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id"), nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("media_storage_key", sa.String(512)),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.CheckConstraint("text IS NOT NULL OR media_storage_key IS NOT NULL", name="ck_shop_testimonial_content"),
    )


def downgrade() -> None:
    """Drop only the catalog tables introduced by this migration."""
    op.drop_table("shop_testimonials")
    op.drop_table("shop_product_media")
    op.drop_table("shop_products")
