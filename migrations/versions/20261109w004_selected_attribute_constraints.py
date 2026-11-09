"""Constrain selected terms to their attribute and prevent duplicates."""

import sqlalchemy as sa
from alembic import op

revision = "20261109w004"
down_revision = "20261109w003"
branch_labels = None
depends_on = None

_LINKS = "shop_product_attribute_links"
_TERMS = "shop_attribute_terms"
_SELECTED = "shop_product_attribute_term_links"


def upgrade() -> None:
    op.add_column(_SELECTED, sa.Column("definition_id", sa.Integer))
    op.execute(sa.text("""
        UPDATE shop_product_attribute_term_links SET definition_id = (
            SELECT definition_id FROM shop_product_attribute_links
            WHERE id = shop_product_attribute_term_links.attribute_id
        )
    """))
    # Keep the first occurrence when historical spellings resolved to one term.
    op.execute(sa.text("""
        DELETE FROM shop_product_attribute_term_links AS duplicate
        WHERE EXISTS (
            SELECT 1 FROM shop_product_attribute_term_links AS first
            WHERE first.attribute_id = duplicate.attribute_id AND first.value_id = duplicate.value_id
            AND (first.position, first.id) < (duplicate.position, duplicate.id)
        )
    """))
    with op.batch_alter_table(_LINKS) as batch:
        batch.create_unique_constraint("uq_shop_attribute_link_definition_id", ["definition_id", "id"])
    with op.batch_alter_table(_TERMS) as batch:
        batch.create_unique_constraint("uq_shop_attribute_term_definition_id", ["definition_id", "id"])
    with op.batch_alter_table(_SELECTED) as batch:
        batch.alter_column("definition_id", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_shop_selected_attribute_term", ["attribute_id", "value_id"])
        batch.create_foreign_key("fk_shop_selected_term_attribute", _LINKS, ["definition_id", "attribute_id"],
                                 ["definition_id", "id"], ondelete="CASCADE", deferrable=True, initially="DEFERRED")
        batch.create_foreign_key("fk_shop_selected_term_definition", _TERMS, ["definition_id", "value_id"],
                                 ["definition_id", "id"], deferrable=True, initially="DEFERRED")
        batch.create_index("ix_shop_product_attribute_term_links_value_id", ["value_id"])


def downgrade() -> None:
    with op.batch_alter_table(_SELECTED) as batch:
        batch.drop_index("ix_shop_product_attribute_term_links_value_id")
        batch.drop_constraint("fk_shop_selected_term_definition", type_="foreignkey")
        batch.drop_constraint("fk_shop_selected_term_attribute", type_="foreignkey")
        batch.drop_constraint("uq_shop_selected_attribute_term", type_="unique")
        batch.drop_column("definition_id")
    with op.batch_alter_table(_TERMS) as batch:
        batch.drop_constraint("uq_shop_attribute_term_definition_id", type_="unique")
    with op.batch_alter_table(_LINKS) as batch:
        batch.drop_constraint("uq_shop_attribute_link_definition_id", type_="unique")
