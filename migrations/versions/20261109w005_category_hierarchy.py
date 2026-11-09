"""Add Store-scoped category parents. Existing categories remain roots."""

import sqlalchemy as sa
from alembic import op

revision = "20261109w005"
down_revision = "20261109w004"
branch_labels = None
depends_on = None

_TABLE = "shop_categories"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer, nullable=True))
        batch.create_unique_constraint("uq_shop_category_store_id", ["store_id", "id"])
        batch.create_foreign_key("fk_shop_category_parent", _TABLE, ["store_id", "parent_id"],
                                 ["store_id", "id"], ondelete="RESTRICT")
        batch.create_check_constraint("ck_shop_category_not_own_parent", "parent_id IS NULL OR parent_id <> id")
        batch.create_index("ix_shop_category_siblings", ["store_id", "parent_id", "position", "id"])


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index("ix_shop_category_siblings")
        batch.drop_constraint("ck_shop_category_not_own_parent", type_="check")
        batch.drop_constraint("fk_shop_category_parent", type_="foreignkey")
        batch.drop_constraint("uq_shop_category_store_id", type_="unique")
        batch.drop_column("parent_id")
