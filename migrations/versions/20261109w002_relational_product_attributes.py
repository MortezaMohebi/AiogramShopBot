"""Move product specifications to linked attribute and value rows.

Revision ID: 20261109w002
Revises: 20261109w001
"""

import sqlalchemy as sa
from alembic import op

revision = "20261109w002"
down_revision = "20261109w001"
branch_labels = None
depends_on = None

products = sa.table("shop_products", sa.column("id", sa.Integer), sa.column("attributes", sa.JSON))


def upgrade() -> None:
    """Backfill every legacy row without deleting the previous storage column."""
    attributes = op.create_table(
        "shop_product_attributes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(48), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(24)),
        sa.Column("visible", sa.Boolean, nullable=False),
        sa.Column("variation", sa.Boolean, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("aliases", sa.JSON, nullable=False),
        sa.Column("external_ids", sa.JSON, nullable=False),
        sa.UniqueConstraint("product_id", "key", name="uq_shop_product_attribute_key"),
    )
    values = op.create_table(
        "shop_product_attribute_values",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attribute_id", sa.Integer, sa.ForeignKey("shop_product_attributes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("external_ids", sa.JSON, nullable=False),
    )
    op.create_index("ix_shop_product_attribute_values_attribute_id", values.name, ["attribute_id"])
    connection = op.get_bind()
    for product in connection.execute(sa.select(products).where(products.c.attributes.is_not(None))):
        for position, item in enumerate(product.attributes or []):
            attribute_id = connection.execute(attributes.insert().values(
                product_id=product.id, key=item["key"], label=item["label"], unit=item.get("unit"),
                visible=item.get("visible", True), variation=item.get("variation", False),
                external_ids=item.get("external_ids", {}), position=position, aliases=[],
            ).returning(attributes.c.id)).scalar_one()
            connection.execute(values.insert(), [
                {"attribute_id": attribute_id, "label": value["label"], "position": index,
                 "external_ids": value.get("external_ids", {})}
                for index, value in enumerate(item["values"])
            ])


def downgrade() -> None:
    """Copy the current data back to the previous representation before dropping tables."""
    connection = op.get_bind()
    metadata = sa.MetaData()
    attributes = sa.Table("shop_product_attributes", metadata, autoload_with=connection)
    values = sa.Table("shop_product_attribute_values", metadata, autoload_with=connection)
    grouped: dict[int, list[dict]] = {}
    for row in connection.execute(sa.select(attributes).order_by(attributes.c.position)).mappings():
        item = {field: row[field] for field in ("key", "label", "unit", "visible", "variation", "external_ids")}
        item["values"] = [dict(value) for value in connection.execute(
            sa.select(values.c.label, values.c.external_ids).where(values.c.attribute_id == row["id"])
            .order_by(values.c.position)
        ).mappings()]
        grouped.setdefault(row["product_id"], []).append(item)
    connection.execute(products.update().values(attributes=[]))
    for product_id, items in grouped.items():
        connection.execute(products.update().where(products.c.id == product_id).values(attributes=items))
    op.drop_table(values.name)
    op.drop_table(attributes.name)
