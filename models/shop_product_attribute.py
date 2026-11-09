"""Store-wide catalog specifications and product-specific selections."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, ForeignKeyConstraint, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base


class ShopAttribute(Base):
    """A reusable specification defined once within a store."""

    __tablename__ = "shop_attribute_definitions"
    __table_args__ = (UniqueConstraint("store_id", "signature", name="uq_shop_attribute_signature"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("shop_stores.id", ondelete="CASCADE"))
    signature: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(24))
    aliases: Mapped[list[str]] = mapped_column(JSON)
    external_ids: Mapped[dict[str, str]] = mapped_column(JSON)


class ShopAttributeValue(Base):
    """A reusable value of one specification."""

    __tablename__ = "shop_attribute_terms"
    __table_args__ = (
        UniqueConstraint("definition_id", "signature", name="uq_shop_attribute_term_signature"),
        UniqueConstraint("definition_id", "id", name="uq_shop_attribute_term_definition_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(ForeignKey("shop_attribute_definitions.id", ondelete="CASCADE"))
    signature: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(80))
    external_ids: Mapped[dict[str, str]] = mapped_column(JSON)


class ShopProductAttribute(Base):
    """A named specification attached to one product."""

    __tablename__ = "shop_product_attribute_links"
    __table_args__ = (
        UniqueConstraint("product_id", "key", name="uq_shop_product_attribute_link_key"),
        UniqueConstraint("definition_id", "id", name="uq_shop_attribute_link_definition_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("shop_products.id", ondelete="CASCADE"))
    definition_id: Mapped[int] = mapped_column(ForeignKey("shop_attribute_definitions.id", ondelete="RESTRICT"))
    definition: Mapped[ShopAttribute] = relationship(lazy="raise")
    key: Mapped[str] = mapped_column(String(48))
    visible: Mapped[bool] = mapped_column(Boolean)
    variation: Mapped[bool] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer)
    values: Mapped[list[ShopProductAttributeValue]] = relationship(
        cascade="all, delete-orphan", order_by="ShopProductAttributeValue.position", lazy="raise",
        foreign_keys="ShopProductAttributeValue.attribute_id",
    )


class ShopProductAttributeValue(Base):
    """A stable value owned by exactly one attribute."""

    __tablename__ = "shop_product_attribute_term_links"
    __table_args__ = (
        UniqueConstraint("attribute_id", "value_id", name="uq_shop_selected_attribute_term"),
        ForeignKeyConstraint(
            ["definition_id", "attribute_id"],
            ["shop_product_attribute_links.definition_id", "shop_product_attribute_links.id"],
            name="fk_shop_selected_term_attribute", ondelete="CASCADE", deferrable=True, initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["definition_id", "value_id"], ["shop_attribute_terms.definition_id", "shop_attribute_terms.id"],
            name="fk_shop_selected_term_definition", deferrable=True, initially="DEFERRED",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attribute_id: Mapped[int] = mapped_column(
        ForeignKey("shop_product_attribute_links.id", ondelete="CASCADE"), index=True,
    )
    value_id: Mapped[int] = mapped_column(ForeignKey("shop_attribute_terms.id", ondelete="RESTRICT"), index=True)
    definition_id: Mapped[int] = mapped_column(Integer)
    value: Mapped[ShopAttributeValue] = relationship(lazy="raise", foreign_keys=[value_id])
    position: Mapped[int] = mapped_column(Integer)
