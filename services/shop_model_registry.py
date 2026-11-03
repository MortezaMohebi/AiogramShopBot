"""Declarative model registry for reusable field search, grouping and data I/O.

Register an SQLAlchemy model with an allowlist of client-visible columns.
Filter, sort, time-bucket, import and export adapters all reuse this metadata
instead of accepting caller-supplied SQL or arbitrary Python attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import ColumnElement
from sqlalchemy.orm import InstrumentedAttribute

from models.shop_content import Product, ShopOrder
from models.shop_store_commerce import ShopStoreCustomer
from services import shop_admin_security as security

DT_FORMATS = ("day", "week", "month", "quarter", "year")
OPS = frozenset({"eq", "ne", "contains", "starts", "gte", "lte", "in"})


@dataclass(frozen=True, slots=True)
class Field:
    """One intentionally exposed field and its validation/search behavior."""

    key: str
    title: str
    kind: str
    column: InstrumentedAttribute | None = None
    sortable: bool = True
    searchable: bool = True
    groupable: bool = False
    importable: bool = False
    exportable: bool = True
    required: bool = False
    max_length: int = 255

    def public(self) -> dict:
        """Expose safe metadata, never SQL identifiers outside this allowlist."""
        return {
            "key": self.key, "title": self.title,
            "kind": self.kind, "sortable": self.sortable,
            "searchable": self.searchable and self.column is not None,
            "groupable": self.groupable,
            "importable": self.importable,
            "exportable": self.exportable,
            "required": self.required,
        }

    def parse(self, raw: Any) -> Any:
        """Normalize one typed filter/import scalar with strict bounds."""
        if raw is None or raw == "":
            return None
        if isinstance(raw, (list, dict)):
            raise security.SecurityRejected("invalid_model_filter", 422)
        if self.kind in {"string", "enum", "uuid"}:
            if not isinstance(raw, str) or len(raw) > self.max_length:
                raise security.SecurityRejected("invalid_model_filter", 422)
            return raw.strip()
        if self.kind in {"integer", "money"}:
            try:
                text = str(raw)
                if not text.lstrip("-").isdigit() or len(text) > 20:
                    raise ValueError
                return int(text)
            except ValueError:
                raise security.SecurityRejected(
                    "invalid_model_filter", 422,
                ) from None
        if self.kind == "boolean":
            if isinstance(raw, bool):
                return raw
            if str(raw).strip().lower() in {"1", "true", "yes"}:
                return True
            if str(raw).strip().lower() in {"0", "false", "no"}:
                return False
            raise security.SecurityRejected("invalid_model_filter", 422)
        if self.kind == "datetime":
            try:
                if not isinstance(raw, str):
                    raise ValueError
                instant = datetime.fromisoformat(
                    raw.replace("Z", "+00:00")
                )
                if instant.tzinfo is None:
                    raise ValueError
                return instant.astimezone(timezone.utc)
            except ValueError:
                raise security.SecurityRejected(
                    "invalid_model_filter", 422,
                ) from None
        raise security.SecurityRejected("invalid_model_filter", 422)


@dataclass(frozen=True, slots=True)
class Dataset:
    """A reusable declarative search/export/import adapter for one model."""

    name: str
    model: type
    label: str
    read_permission: str
    write_permission: str | None
    fields: tuple[Field, ...]
    primary_order: str = "id"

    def field(self, key: str, *, intent: str = "read") -> Field:
        """Require a registered column; never resolve arbitrary attribute."""
        item = next((field for field in self.fields if field.key == key), None)
        if item is None or (
            intent == "search" and (
                not item.searchable or item.column is None
            )
        ) or (
            intent == "sort" and (
                not item.sortable or item.column is None
            )
        ) or (
            intent == "group" and (
                not item.groupable or item.column is None
            )
        ) or (
            intent == "import" and not item.importable
        ) or (
            intent == "export" and not item.exportable
        ):
            raise security.SecurityRejected("unknown_model_field", 422)
        return item

    def metadata(self) -> dict:
        """Describe the same safe columns used by every data operation."""
        return {
            "model": self.name, "label": self.label,
            "can_import": self.write_permission is not None,
            "fields": [item.public() for item in self.fields],
            "time_granularities": list(DT_FORMATS),
        }


PRODUCT = Dataset(
    "products", Product, "محصولات", "catalog.read", "catalog.write",
    (
        Field("id", "ID", "integer", Product.id, importable=False),
        Field("external_ref", "شناسه خارجی", "string", Product.external_ref,
              importable=True, max_length=80),
        Field("sku", "SKU", "string", Product.sku,
              importable=True, max_length=64),
        Field("name", "نام محصول", "string", Product.name,
              importable=True, required=True),
        Field("description", "توضیحات", "string", Product.description,
              importable=True, sortable=False, max_length=40_000),
        Field("price_irr", "قیمت (ریال)", "money", Product.price,
              importable=True, required=True),
        Field("stock_quantity", "موجودی", "integer", Product.stock_quantity,
              importable=True),
        Field("product_type", "نوع محصول", "enum", Product.product_type,
              importable=True, groupable=True, max_length=12),
        Field("requires_shipping", "نیازمند ارسال", "boolean",
              Product.requires_shipping, importable=True, groupable=True),
        Field("price_stars", "قیمت Stars", "integer", Product.price_stars,
              importable=True),
        Field("is_published", "منتشرشده", "boolean", Product.is_published,
              importable=True, groupable=True),
        Field("category_id", "دسته‌بندی", "integer", Product.category_id,
              importable=True, groupable=True),
        Field("uom_code", "واحد فروش", "string", None, importable=True,
              searchable=False, sortable=False, max_length=32),
        Field("purchase_uom_code", "واحد خرید", "string", None,
              importable=True, searchable=False, sortable=False, max_length=32),
        Field("store_id", "Store", "uuid", Product.store_id,
              sortable=False, importable=False, max_length=36),
    ),
)

CUSTOMER = Dataset(
    "customers", ShopStoreCustomer, "مشتریان فروشگاه",
    "customers.read", "customers.read",
    (
        Field("id", "ID", "integer", ShopStoreCustomer.id),
        Field("external_ref", "شناسه خارجی", "string",
              ShopStoreCustomer.external_ref, importable=True, max_length=80),
        Field("display_name", "نام مشتری", "string",
              ShopStoreCustomer.display_name, importable=True, max_length=255),
        Field("phone", "تلفن", "string", ShopStoreCustomer.phone,
              importable=True, max_length=32),
        Field("created_at", "تاریخ ایجاد", "datetime",
              ShopStoreCustomer.created_at, groupable=True),
        Field("store_id", "Store", "uuid", ShopStoreCustomer.store_id,
              sortable=False, max_length=36),
    ),
)

ORDER = Dataset(
    "orders", ShopOrder, "سفارش‌ها", "orders.read", None,
    (
        Field("id", "ID", "integer", ShopOrder.id),
        Field("status", "وضعیت", "enum", ShopOrder.status,
              groupable=True, max_length=24),
        Field("platform", "پیام‌رسان", "enum", ShopOrder.platform,
              groupable=True, max_length=12),
        Field("provider", "Provider", "enum", ShopOrder.provider,
              groupable=True, max_length=24),
        Field("total_irr", "مبلغ (ریال)", "money", ShopOrder.total_irr),
        Field("created_at", "تاریخ ایجاد", "datetime",
              ShopOrder.created_at, groupable=True),
        Field("paid_at", "تاریخ پرداخت", "datetime",
              ShopOrder.paid_at, groupable=True),
        Field("store_id", "Store", "uuid", ShopOrder.store_id,
              sortable=False, max_length=36),
    ),
)

REGISTRY: dict[str, Dataset] = {
    dataset.name: dataset for dataset in (PRODUCT, CUSTOMER, ORDER)
}


def get_dataset(name: str) -> Dataset:
    """Retrieve only explicitly registered, permission-described models."""
    dataset = REGISTRY.get(name)
    if dataset is None:
        raise security.SecurityRejected("unknown_model", 404)
    return dataset


def escape_like(value: str) -> str:
    """Treat wildcard and escape characters as literal user input."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace(
        "_", "\\_",
    )


def filtered_clause(field: Field, operator: str, raw: Any) -> ColumnElement:
    """Construct a typed SQLAlchemy expression without client SQL strings."""
    if operator not in OPS:
        raise security.SecurityRejected("invalid_model_operator", 422)
    column = field.column
    if column is None:
        raise security.SecurityRejected("unknown_model_field", 422)
    if operator == "in":
        if not isinstance(raw, list) or not 1 <= len(raw) <= 20:
            raise security.SecurityRejected("invalid_model_filter", 422)
        values = [field.parse(item) for item in raw]
        if any(item is None for item in values):
            raise security.SecurityRejected("invalid_model_filter", 422)
        return column.in_(values)
    value = field.parse(raw)
    if value is None:
        if operator == "eq":
            return column.is_(None)
        if operator == "ne":
            return column.is_not(None)
        raise security.SecurityRejected("invalid_model_filter", 422)
    if operator in {"contains", "starts"}:
        if field.kind not in {"string", "enum"}:
            raise security.SecurityRejected("invalid_model_operator", 422)
        term = escape_like(value)
        return column.ilike(
            f"%{term}%" if operator == "contains" else f"{term}%",
            escape="\\",
        )
    if operator == "eq":
        return column == value
    if operator == "ne":
        return column != value
    if operator == "gte":
        return column >= value
    if operator == "lte":
        return column <= value
    raise security.SecurityRejected("invalid_model_operator", 422)


def safe_value(value: Any) -> str | int | bool | None:
    """Serialize bounded, non-secret CSV/JSON scalar fields."""
    if value is None:
        return None
    if isinstance(value, (datetime,)):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bool, int)):
        return value
    return str(value)
