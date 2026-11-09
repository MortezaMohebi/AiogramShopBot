"""Validate ordered product specifications and render their public values."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from models.shop_content import Product
from models.shop_multibot import ShopStore
from models.shop_product_attribute import ShopAttribute, ShopAttributeValue, ShopProductAttribute, ShopProductAttributeValue
from models.shop_uom import ShopUom
from services.shop_attribute_identity import definition_signature_v1, term_signature_v1
from utils.shop_text import clean_text

ATTRIBUTE_DETAIL_LIMIT = 1500
_Source = Annotated[str, Field(pattern=r"^[a-z][a-z0-9:_-]{0,39}$")]
_ExternalID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:/-]{1,80}$")]
_ExternalIDs = Annotated[dict[_Source, _ExternalID], Field(max_length=4)]


def _label(value: str) -> str:
    value = clean_text(value)
    if not value:
        raise ValueError("An attribute label is required")
    return value


_Label = Annotated[str, Field(min_length=1, max_length=80), AfterValidator(_label)]


class ProductAttributeValue(BaseModel):
    """One display value with optional identifiers in connected catalogs."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: int | None = Field(default=None, gt=0)
    value_id: int | None = Field(default=None, gt=0)
    label: _Label
    external_ids: _ExternalIDs = Field(default_factory=dict)


class ProductAttribute(BaseModel):
    """An ordered product attribute independent of a particular connector."""

    model_config = ConfigDict(extra="forbid", strict=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,47}$")
    definition_id: int | None = Field(default=None, gt=0)
    label: _Label
    values: list[ProductAttributeValue] = Field(min_length=1, max_length=8)
    unit: Annotated[str, Field(min_length=1, max_length=24), AfterValidator(_label)] | None = None
    aliases: list[_Label] = Field(default_factory=list, max_length=6)
    visible: bool = True
    variation: bool = False
    external_ids: _ExternalIDs = Field(default_factory=dict)


def attribute_values(attribute: dict) -> str:
    """Format values and units without exposing connection identifiers."""
    unit = attribute.get("unit_label") or attribute.get("unit")
    return "، ".join(
        f"{value['label']} {unit}" if unit else value["label"]
        for value in attribute["values"]
    )


def public_attributes(attributes: list[dict] | None) -> str:
    """Render only customer-visible rows, preserving editor order."""
    return "\n".join(
        f"{attribute['label']}: {attribute_values(attribute)}"
        for attribute in attributes or [] if attribute.get("visible", True)
    )


def match_attributes(attributes: list[dict], question: str) -> tuple[list[dict], str]:
    """Find configured names in a normalized question and strip their words."""
    from services.shop_customer_search import normalize_persian

    matches = []
    remaining = question
    for attribute in attributes:
        terms = {
            normalize_persian(term) for term in (
                attribute["key"], attribute["label"], *attribute["aliases"],
                attribute.get("unit"), attribute.get("unit_label"), attribute.get("unit_symbol"),
            ) if term
        }
        choices = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
        pattern = re.compile(r"(?<!\w)(?:" + choices + r")ش?(?!\w)")
        if pattern.search(question):
            matches.append(attribute)
            remaining = pattern.sub(" ", remaining)
    return matches, remaining


def _validate_attributes(attributes: list[ProductAttribute]) -> list[ProductAttribute]:
    if len({attribute.key for attribute in attributes}) != len(attributes):
        raise ValueError("Attribute keys must be unique within the product")
    for attribute in attributes:
        labels = {value.value_id or term_signature_v1(value.label, {}) for value in attribute.values}
        ids = [value.id for value in attribute.values if value.id is not None]
        if len(labels) != len(attribute.values):
            raise ValueError("An attribute cannot repeat a value")
        if len(set(ids)) != len(ids):
            raise ValueError("An attribute cannot repeat a value ID")
    if len(public_attributes([attribute.model_dump() for attribute in attributes])) > ATTRIBUTE_DETAIL_LIMIT:
        raise ValueError("Visible attributes exceed the card detail limit")
    return attributes


ProductAttributes = Annotated[
    list[ProductAttribute], Field(max_length=12), AfterValidator(_validate_attributes),
]


async def _rows(db: AsyncSession, product_id: int) -> list[ShopProductAttribute]:
    return list((await db.scalars(select(ShopProductAttribute).join(
        Product, Product.id == ShopProductAttribute.product_id,
    ).join(ShopProductAttribute.definition).where(
        ShopProductAttribute.product_id == product_id,
        ShopAttribute.store_id == Product.store_id,
    ).options(
        selectinload(ShopProductAttribute.definition),
        selectinload(ShopProductAttribute.values).selectinload(ShopProductAttributeValue.value),
    ).order_by(ShopProductAttribute.position))).all())


def _definition_data(definition: ShopAttribute) -> dict:
    return {"definition_id": definition.id, "label": definition.label, "unit": definition.unit,
            "aliases": definition.aliases, "external_ids": definition.external_ids}


def _term_data(term: ShopAttributeValue) -> dict:
    return {"value_id": term.id, "label": term.label, "external_ids": term.external_ids}


async def attribute_options(db: AsyncSession, store_id: str) -> list[dict]:
    """Return a bounded set of reusable choices scoped to the authorized store."""
    definitions = (await db.scalars(select(ShopAttribute).where(ShopAttribute.store_id == store_id)
                   .order_by(ShopAttribute.label, ShopAttribute.id).limit(100))).all()
    options = {definition.id: {**_definition_data(definition), "values": []} for definition in definitions}
    if options:
        ranked = select(ShopAttributeValue, func.row_number().over(
            partition_by=ShopAttributeValue.definition_id, order_by=ShopAttributeValue.id,
        ).label("position")).where(ShopAttributeValue.definition_id.in_(options)).subquery()
        term = aliased(ShopAttributeValue, ranked)
        for value in (await db.scalars(select(term).where(ranked.c.position <= 30).order_by(term.id))).all():
            options[value.definition_id]["values"].append(_term_data(value))
    return list(options.values())


async def read_product_attributes(
    db: AsyncSession, product_id: int, *, display_store_id: str | None = None,
) -> list[dict]:
    """Load an authorized product's specs, resolving its Store's units for display."""
    rows = await _rows(db, product_id)
    codes = {row.definition.unit for row in rows if row.definition.unit}
    units = {}
    if display_store_id and codes:
        units = {unit.code: unit for unit in (await db.scalars(select(ShopUom).where(
            ShopUom.store_id == display_store_id, ShopUom.code.in_(codes),
        ))).all()}
    items = []
    for row in rows:
        item = {
            **_definition_data(row.definition), "key": row.key,
            "visible": row.visible, "variation": row.variation,
            "values": [
                {"id": value.id, **_term_data(value.value)}
                for value in row.values if value.value.definition_id == row.definition_id
            ],
        }
        if row.definition.unit in units:
            unit = units[row.definition.unit]
            item.update(unit_label=unit.name, unit_symbol=unit.symbol)
        items.append(item)
    return items


async def save_product_attributes(db: AsyncSession, product_id: int, attributes: list[dict]) -> None:
    """Update product selections while retaining shared definitions and terms."""
    store_id = await db.scalar(select(Product.store_id).where(Product.id == product_id))
    if store_id is None:
        raise ValueError("Product does not exist")
    current = {row.key: row for row in await _rows(db, product_id)}
    for item in attributes:
        row = current.get(item["key"])
        owned = {value.id for value in row.values} if row else set()
        if any(value.get("id") is not None and value["id"] not in owned for value in item["values"]):
            raise ValueError("Attribute value belongs to another attribute")

    if attributes:
        # Serialize creation of identical definitions from different products.
        await db.scalar(select(ShopStore.id).where(ShopStore.id == store_id).with_for_update())

    for position, item in enumerate(attributes):
        key = item["key"]
        row = current.pop(key, None)
        if item.get("definition_id") is not None:
            definition = await db.scalar(select(ShopAttribute).where(
                ShopAttribute.store_id == store_id, ShopAttribute.id == item["definition_id"],
            ))
            if definition is None:
                raise ValueError("Attribute does not belong to this store")
        else:
            fields = {field: item[field] for field in ("label", "unit", "aliases", "external_ids")}
            signature = definition_signature_v1(**fields)
            definition = await db.scalar(select(ShopAttribute).where(
                ShopAttribute.store_id == store_id, ShopAttribute.signature == signature,
            ))
            if definition is None:
                definition = ShopAttribute(store_id=store_id, signature=signature, **fields)
                db.add(definition)
                await db.flush()
        signatures = {term_signature_v1(value["label"], value["external_ids"]) for value in item["values"]}
        terms = {term.signature: term for term in (await db.scalars(select(ShopAttributeValue).where(
            ShopAttributeValue.definition_id == definition.id, ShopAttributeValue.signature.in_(signatures),
        ))).all()}
        if row is None:
            row = ShopProductAttribute(product_id=product_id, key=key, values=[])
            db.add(row)
        row.definition = definition
        row.position = position
        row.visible = item["visible"]
        row.variation = item["variation"]
        by_id = {value.id: value for value in row.values}
        claimed = {value["id"] for value in item["values"] if value.get("id") is not None}
        by_label = {term_signature_v1(value.value.label, {}): value for value in row.values if value.id not in claimed}
        values = []
        selected = set()
        used_links = set()
        requested_terms = {value.get("value_id") for value in item["values"]} - {None}
        for index, item_value in enumerate(item["values"]):
            label = item_value["label"]
            external_ids = item_value["external_ids"]
            signature = term_signature_v1(label, external_ids)
            if item_value.get("value_id") is not None:
                term = await db.scalar(select(ShopAttributeValue).where(
                    ShopAttributeValue.definition_id == definition.id, ShopAttributeValue.id == item_value["value_id"],
                ))
                if term is None:
                    raise ValueError("Value does not belong to this attribute")
            else:
                term = terms.get(signature)
            if term is None:
                term = ShopAttributeValue(definition_id=definition.id, signature=signature, label=label, external_ids=external_ids)
                terms[signature] = term
            if term.signature in selected:
                raise ValueError("An attribute cannot repeat a value")
            selected.add(term.signature)
            value = next((link for link in row.values if link.value_id == term.id and term.id is not None), None)
            if value is None:
                candidate = by_id.get(item_value.get("id")) or by_label.get(term_signature_v1(label, {}))
                if candidate is not None and candidate.value_id not in requested_terms and candidate not in used_links:
                    value = candidate
            if value is None:
                value = ShopProductAttributeValue()
            used_links.add(value)
            value.value = term
            value.definition_id = definition.id
            value.position = index
            values.append(value)
        row.values = values
    for row in current.values():
        await db.delete(row)
