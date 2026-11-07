"""Reusable, bounded SQLAlchemy query/search/group-by for registered models.

No caller-provided table or column name is interpolated into SQL. The
registry selects fixed ORM attributes, every query explicitly restricts
rows to active Store IDs, and time buckets are normalized to UTC.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, cast, func, literal, select, Integer
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.orm import InstrumentedAttribute
from services import shop_admin_security as security
from services.shop_model_registry import (
    DT_FORMATS, Dataset, Field, filtered_clause, safe_value,
)
from services.shop_store_context import StoreContext, current_context

MAX_FILTERS = 10
MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 5_000
MAX_EXPORT_BYTES = 16 * 1024 * 1024


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
    """Serialize registered ORM attributes and computed fields generically.

    Computed fields are registered as SQLAlchemy expressions in the Dataset
    declaration. Resolve them in bounded batched selects, never by N+1
    queries or hardcoded per-model special cases.
    """
    fields = [field for field in dataset.fields if field.exportable]
    computed = [
        field for field in fields
        if field.column is not None
        and not isinstance(field.column, InstrumentedAttribute)
    ]
    computed_values: dict[Any, dict[str, Any]] = {}
    if computed and rows:
        # Bound IN-list size for SQLite/PostgreSQL and avoid large packets.
        identifiers = [getattr(row, dataset.primary_order) for row in rows]
        for offset in range(0, len(identifiers), 300):
            window = identifiers[offset:offset + 300]
            records = (await db.execute(select(
                dataset.model.id,
                *(field.column.label(field.key) for field in computed),
            ).where(
                dataset.model.id.in_(window),
                *predicate(dataset, []),
            ))).all()
            for record in records:
                computed_values[record[0]] = {
                    field.key: record[index + 1]
                    for index, field in enumerate(computed)
                }
    result = []
    for row in rows:
        pk = getattr(row, dataset.primary_order)
        values = computed_values.get(pk, {})
        record = {}
        for field in fields:
            if isinstance(field.column, InstrumentedAttribute):
                value = getattr(row, field.column.key)
            elif field.column is not None:
                value = values.get(field.key)
            else:
                value = None
            # Never round large IRR amounts through JavaScript Number.
            record[field.key] = (
                str(value) if (field.kind == "money" or field.key == "id") and value is not None
                else safe_value(value)
            )
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
        if granularity == "quarter":
            month = cast(func.strftime("%m", field.column), Integer)
            label = case(
                (month <= 3, "Q1"), (month <= 6, "Q2"),
                (month <= 9, "Q3"), else_="Q4",
            )
            return func.strftime("%Y", field.column) + "-" + label
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
    db: AsyncSession, dataset: Dataset, *,
    fields: Sequence[str] | None = None,
    current_store_only: bool = False,
    max_rows: int = MAX_EXPORT_ROWS,
    selected_ids: Sequence[int] | None = None,
) -> tuple[list[str], list[dict]]:
    """Return a deterministic, bounded snapshot for CSV/XLSX export."""
    ctx = trusted_context()
    headers = list(fields) if fields is not None else [
        field.key for field in dataset.fields if field.exportable
    ]
    columns = [dataset.field(key, intent="export") for key in headers]
    store_ids = (ctx.current_store_id,) if current_store_only else ctx.active_store_ids
    scope = dataset.model.store_id.in_(store_ids)
    if selected_ids is not None:
        if (not 1 <= len(selected_ids) <= 100
            or any(type(item) is not int or item < 1 or item > 9_223_372_036_854_775_807
                   for item in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)):
            raise security.SecurityRejected("invalid_model_selection", 422)
        scope = scope & dataset.model.id.in_(selected_ids)
    total = int(await db.scalar(select(func.count()).select_from(
        dataset.model,
    ).where(scope)) or 0)
    if selected_ids is not None and total != len(selected_ids):
        raise security.SecurityRejected("model_selection_changed", 409)
    if total > max_rows:
        raise security.SecurityRejected("model_export_too_large", 409)
    # Reject oversized text sets BEFORE materializing thousands of Product
    # descriptions into Python memory. The encoder also checks real UTF-8
    # output bytes, including Farsi multibyte characters and CSV quoting.
    long_texts = [
        field for field in columns
        if field.max_length > 1000
        and isinstance(field.column, InstrumentedAttribute)
    ]
    for field in long_texts:
        total_chars = int(await db.scalar(select(
            func.coalesce(func.sum(func.length(field.column)), 0),
        ).where(scope)) or 0)
        if total_chars > MAX_EXPORT_BYTES:
            raise security.SecurityRejected("model_export_too_large", 409)
    records = (await db.execute(select(*[
        (field.column if field.column is not None else literal(None)).label(field.key)
        for field in columns
    ]).select_from(dataset.model).where(scope)
        .order_by(dataset.model.id.asc()).limit(max_rows + 1))).mappings().all()
    if len(records) > max_rows:
        raise security.SecurityRejected("model_export_too_large", 409)
    return headers, [{
        field.key: (
            str(row[field.key]) if field.kind == "money" and row[field.key] is not None
            else safe_value(row[field.key])
        )
        for field in columns
    } for row in records]
