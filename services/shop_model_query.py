"""Reusable, bounded SQLAlchemy query/search/group-by for registered models.

No caller-provided table or column name is interpolated into SQL. The
registry selects fixed ORM attributes, every query explicitly restricts
rows to active Store IDs, and time buckets are normalized to UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import Product
from models.shop_uom import ShopUom
from services import shop_admin_security as security
from services.shop_model_registry import (
    DT_FORMATS, Dataset, Field, filtered_clause, safe_value,
)
from services.shop_store_context import StoreContext, current_context

MAX_FILTERS = 10
MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 5_000


def trusted_context() -> StoreContext:
    """Reject any model query lacking a signed admin Store environment."""
    context = current_context()
    if not isinstance(context, StoreContext):
        raise security.SecurityRejected("store_access_denied", 403)
    return context


def predicate(
    dataset: Dataset, filters: Sequence[dict[str, Any]],
):
    """Combine Store fencing with at most ten allowlisted field predicates."""
    ctx = trusted_context()
    if not isinstance(filters, (list, tuple)) or len(filters) > MAX_FILTERS:
        raise security.SecurityRejected("invalid_model_filter", 422)
    clauses = [dataset.model.store_id.in_(ctx.active_store_ids)]
    for item in filters:
        if not isinstance(item, dict) or set(item) != {
            "field", "op", "value",
        }:
            raise security.SecurityRejected("invalid_model_filter", 422)
        field = dataset.field(item["field"], intent="search")
        clauses.append(filtered_clause(field, item["op"], item["value"]))
    return clauses


async def serialize_rows(
    db: AsyncSession, dataset: Dataset, rows: Sequence,
) -> list[dict]:
    """Serialize only fields exposed by the same registry definition."""
    units: dict[str, str] = {}
    if dataset.name == "products" and rows:
        identifiers = {
            identifier for item in rows
            for identifier in (item.uom_id, item.purchase_uom_id)
            if identifier
        }
        units = dict((await db.execute(
            select(ShopUom.id, ShopUom.code).where(
                ShopUom.id.in_(identifiers),
                ShopUom.store_id.in_(trusted_context().active_store_ids),
            )
        )).all())
    result = []
    for row in rows:
        record = {}
        for field in dataset.fields:
            if not field.exportable:
                continue
            if field.key == "uom_code":
                value = units.get(row.uom_id)
            elif field.key == "purchase_uom_code":
                value = units.get(row.purchase_uom_id)
            elif field.column is not None:
                value = getattr(row, field.column.key)
            else:
                continue
            record[field.key] = safe_value(value)
        result.append(record)
    return result


async def search(
    db: AsyncSession, dataset: Dataset, *, filters: list[dict[str, Any]],
    page: int, page_size: int, sort_by: str, descending: bool,
) -> dict:
    """Page a single model by safe, typed filters with exact Store boundaries."""
    if (
        type(page) is not int or not 1 <= page <= 100_000
        or type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE
        or type(descending) is not bool
    ):
        raise security.SecurityRejected("invalid_model_pagination", 422)
    sort_field = dataset.field(sort_by, intent="sort")
    clauses = predicate(dataset, filters)
    total = int(await db.scalar(
        select(func.count()).select_from(dataset.model).where(*clauses)
    ) or 0)
    ordering = (
        sort_field.column.desc() if descending else sort_field.column.asc()
    )
    rows = (await db.scalars(
        select(dataset.model).where(*clauses)
        .order_by(ordering, dataset.model.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all()
    return {
        "model": dataset.name, "page": page,
        "page_size": page_size, "total": total,
        "items": await serialize_rows(db, dataset, rows),
    }


def _date_bucket(db: AsyncSession, field: Field, granularity: str):
    """Use a normalized UTC bucket, with a SQLite offline-test fallback."""
    if granularity not in DT_FORMATS or field.kind != "datetime":
        raise security.SecurityRejected("invalid_model_group", 422)
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        fmt = {
            "day": "%Y-%m-%d",
            "week": "%Y-W%W",
            "month": "%Y-%m",
            "quarter": "%Y-%m",
            "year": "%Y",
        }[granularity]
        return func.strftime(fmt, field.column)
    # PostgreSQL: timestamptz -> UTC wall clock -> explicit bucket.
    return func.date_trunc(
        granularity, func.timezone("UTC", field.column),
    )


async def group_by(
    db: AsyncSession, dataset: Dataset, *, field_name: str,
    granularity: str | None, filters: list[dict[str, Any]],
) -> dict:
    """Count records by safe field or UTC day/week/month/quarter/year."""
    field = dataset.field(field_name, intent="group")
    if field.kind == "datetime":
        bucket = _date_bucket(db, field, granularity or "month")
    else:
        if granularity is not None:
            raise security.SecurityRejected("invalid_model_group", 422)
        bucket = field.column
    clauses = predicate(dataset, filters)
    rows = (await db.execute(
        select(bucket.label("bucket"), func.count(dataset.model.id))
        .where(*clauses)
        .group_by(bucket).order_by(bucket).limit(500)
    )).all()
    return {
        "model": dataset.name, "field": field_name,
        "granularity": granularity or (
            "month" if field.kind == "datetime" else None
        ),
        "timezone": "UTC" if field.kind == "datetime" else None,
        "items": [{
            "bucket": safe_value(value), "count": int(count),
        } for value, count in rows],
    }


async def export_records(
    db: AsyncSession, dataset: Dataset,
) -> tuple[list[str], list[dict]]:
    """Return a deterministic, bounded snapshot for CSV/XLSX export."""
    ctx = trusted_context()
    total = int(await db.scalar(select(func.count()).select_from(
        dataset.model,
    ).where(
        dataset.model.store_id.in_(ctx.active_store_ids),
    )) or 0)
    if total > MAX_EXPORT_ROWS:
        raise security.SecurityRejected("model_export_too_large", 409)
    records = (await db.scalars(
        select(dataset.model).where(
            dataset.model.store_id.in_(ctx.active_store_ids),
        ).order_by(dataset.model.id.asc()).limit(MAX_EXPORT_ROWS)
    )).all()
    headers = [field.key for field in dataset.fields if field.exportable]
    return headers, await serialize_rows(db, dataset, records)
