"""Share product attribute definitions and terms within each store."""

import hashlib
import json
import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "20261109w003"
down_revision = "20261109w002"
branch_labels = None
depends_on = None

# Keep the identity algorithm frozen for older migration histories.
_VARIANTS = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " ",
    **dict(zip("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "0123456789" * 2)),
})


def _canonical(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).translate(_VARIANTS).casefold().split())


def _signature(parts: list) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def upgrade() -> None:
    definitions = op.create_table(
        "shop_attribute_definitions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("store_id", sa.String(36), sa.ForeignKey("shop_stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("unit", sa.String(24)),
        sa.Column("aliases", sa.JSON, nullable=False),
        sa.Column("external_ids", sa.JSON, nullable=False),
        sa.UniqueConstraint("store_id", "signature", name="uq_shop_attribute_signature"),
    )
    terms = op.create_table(
        "shop_attribute_terms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("definition_id", sa.Integer, sa.ForeignKey(definitions.c.id, ondelete="CASCADE"), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("external_ids", sa.JSON, nullable=False),
        sa.UniqueConstraint("definition_id", "signature", name="uq_shop_attribute_term_signature"),
    )
    links = op.create_table(
        "shop_product_attribute_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("product_id", sa.Integer, sa.ForeignKey("shop_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("definition_id", sa.Integer, sa.ForeignKey(definitions.c.id, ondelete="RESTRICT"), nullable=False),
        sa.Column("key", sa.String(48), nullable=False),
        sa.Column("visible", sa.Boolean, nullable=False),
        sa.Column("variation", sa.Boolean, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.UniqueConstraint("product_id", "key", name="uq_shop_product_attribute_link_key"),
    )
    selections = op.create_table(
        "shop_product_attribute_term_links",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("attribute_id", sa.Integer, sa.ForeignKey(links.c.id, ondelete="CASCADE"), nullable=False),
        sa.Column("value_id", sa.Integer, sa.ForeignKey(terms.c.id, ondelete="RESTRICT"), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
    )
    op.create_index("ix_shop_product_attribute_term_links_attribute_id", selections.name, ["attribute_id"])
    connection = op.get_bind()
    meta = sa.MetaData()
    old_attributes = sa.Table("shop_product_attributes", meta, autoload_with=connection)
    old_values = sa.Table("shop_product_attribute_values", meta, autoload_with=connection)
    products = sa.Table("shop_products", meta, autoload_with=connection)
    definition_ids = {}
    link_ids = {}
    term_ids = {}

    for item in connection.execute(sa.select(old_attributes, products.c.store_id)
                                   .join(products, products.c.id == old_attributes.c.product_id)
                                   .order_by(old_attributes.c.id)).mappings():
        data = {key: item[key] for key in ("label", "unit", "aliases", "external_ids")}
        signature = _signature([_canonical(data["label"]), _canonical(data["unit"] or ""),
                                sorted({_canonical(a) for a in data["aliases"]}), data["external_ids"]])
        owner = (item["store_id"], signature)
        if owner not in definition_ids:
            definition_ids[owner] = connection.execute(definitions.insert().values(
                store_id=item["store_id"], signature=signature, **data,
            ).returning(definitions.c.id)).scalar_one()
        definition_id = definition_ids[owner]
        link_ids[item["id"]] = definition_id
        connection.execute(links.insert().values(definition_id=definition_id, **{
            key: item[key] for key in ("id", "product_id", "key", "visible", "variation", "position")
        }))

    for item in connection.execute(sa.select(old_values).order_by(old_values.c.id)).mappings():
        definition_id = link_ids[item["attribute_id"]]
        signature = _signature([_canonical(item["label"]), item["external_ids"]])
        owner = (definition_id, signature)
        if owner not in term_ids:
            term_ids[owner] = connection.execute(terms.insert().values(
                definition_id=definition_id, signature=signature, label=item["label"], external_ids=item["external_ids"],
            ).returning(terms.c.id)).scalar_one()
        connection.execute(selections.insert().values(
            id=item["id"], attribute_id=item["attribute_id"], position=item["position"], value_id=term_ids[owner],
        ))
    if connection.dialect.name == "postgresql":
        for table in (links, selections):
            connection.execute(sa.select(sa.func.setval(sa.func.pg_get_serial_sequence(table.name, "id"),
                               sa.func.coalesce(sa.func.max(table.c.id), 1), sa.func.count() > 0)))


def downgrade() -> None:
    raise RuntimeError("Shared catalog definitions cannot be downgraded without losing reuse data")
