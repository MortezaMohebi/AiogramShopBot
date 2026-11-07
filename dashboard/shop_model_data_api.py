"""Generic authenticated Search, GroupBy and CSV/XLSX data exchange API.

Model-specific code is limited to the declarative Dataset registry and
validated import adapters. These endpoints never accept arbitrary SQL,
unbounded exports, platform bot tokens, or client Store ownership claims.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.next_api import database, signed_staff
from dashboard.admin_control_api import StrictPayload
from models.shop_staff import ShopStaff
from services import shop_admin_security as security
from services import shop_model_io as data_io
from services import shop_import_preview as previews
from services import shop_model_query as engine
from services.shop_model_registry import REGISTRY, get_dataset
from services.shop_store_context import current_context

router = APIRouter(prefix="/internal/admin/v1", tags=["Model data"])
Db = Annotated[AsyncSession, Depends(database)]
Actor = Annotated[ShopStaff | None, Depends(signed_staff)]


class Filter(StrictPayload):
    """One bounded, field-allowlisted typed condition."""

    field: str = Field(min_length=1, max_length=64)
    op: Literal["eq", "ne", "contains", "starts", "gte", "lte", "in"]
    value: str | int | bool | list[str | int | bool] | None


class Search(StrictPayload):
    """Reusable model search and pagination request."""

    filters: list[Filter] = Field(default_factory=list, max_length=10)
    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=30, ge=1, le=100)
    sort_by: str = Field(default="id", max_length=64)
    descending: bool = True


class Group(StrictPayload):
    """Group a registered field or a UTC date bucket."""

    filters: list[Filter] = Field(default_factory=list, max_length=10)
    field: str = Field(min_length=1, max_length=64)
    granularity: Literal["day", "week", "month", "quarter", "year"] | None = None


def authorize(
    actor: ShopStaff | None, model_name: str, *,
    write: bool = False,
):
    """Require both a known dataset and explicit backend role permission."""
    dataset = get_dataset(model_name)
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    required = (
        dataset.write_permission if write else dataset.read_permission
    )
    if required is None:
        raise security.SecurityRejected("model_import_not_supported", 405)
    security.require_permission(actor.role, required)
    scope = current_context()
    if scope is None:
        raise security.SecurityRejected("store_access_denied", 403)
    if write:
        scope.require(scope.current_store_id, write=True)
    return dataset


@router.get("/data-models")
async def list_models(actor: Actor) -> dict:
    """Show only models authorized by the signed user's effective role."""
    if actor is None:
        raise security.SecurityRejected("session_expired", 401)
    return {"items": [
        {
            **dataset.metadata(),
            "can_import": bool(
                dataset.write_permission and security.has_permission(
                    actor.role, dataset.write_permission,
                )
            ),
        }
        for dataset in REGISTRY.values()
        if security.has_permission(actor.role, dataset.read_permission)
    ]}


@router.get("/data-models/{model_name}")
async def describe_model(model_name: str, actor: Actor) -> dict:
    """Expose reusable field/operator metadata and no SQL implementation."""
    dataset = authorize(actor, model_name)
    return {
        **dataset.metadata(),
        "can_import": bool(
            dataset.write_permission and security.has_permission(
                actor.role, dataset.write_permission,
            )
        ),
    }


@router.post("/data-models/{model_name}/search")
async def search_model(
    model_name: str, payload: Search, actor: Actor, db: Db,
) -> dict:
    """Filter by user-selected registered fields, order, and bounded page."""
    dataset = authorize(actor, model_name)
    return await engine.search(
        db, dataset,
        filters=[item.model_dump() for item in payload.filters],
        page=payload.page, page_size=payload.page_size,
        sort_by=payload.sort_by, descending=payload.descending,
    )


@router.post("/data-models/{model_name}/group")
async def grouped_model(
    model_name: str, payload: Group, actor: Actor, db: Db,
) -> dict:
    """Count time-sensitive rows by UTC period or allowed categorical field."""
    dataset = authorize(actor, model_name)
    return await engine.group_by(
        db, dataset, field_name=payload.field,
        granularity=payload.granularity,
        filters=[item.model_dump() for item in payload.filters],
    )


@router.get("/data-models/{model_name}/template")
async def template(
    model_name: str, actor: Actor,
    format_name: Literal["csv", "xlsx"] = Query(alias="format"),
) -> Response:
    """Generate a safe empty import template with model field definitions."""
    dataset = authorize(actor, model_name, write=True)
    payload, media = data_io.encode_table(
        dataset, format_name=format_name, rows=[], template=True,
    )
    return Response(
        content=payload, media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{model_name}-template.{format_name}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/data-models/{model_name}/export")
async def export_model(
    model_name: str, actor: Actor, db: Db,
    format_name: Literal["csv", "xlsx"] = Query(alias="format"),
    fields: Annotated[list[str] | None, Query(max_length=40)] = None,
    update_compatible: bool = False,
) -> Response:
    """Export at most 5,000 records from only selected, authorized Stores."""
    dataset = authorize(actor, model_name)
    if update_compatible:
        authorize(actor, model_name, write=True)
    headers = data_io.export_headers(
        dataset, fields=fields, update_compatible=update_compatible,
    )
    _, records = await engine.export_records(
        db, dataset, fields=headers, current_store_only=update_compatible,
        max_rows=data_io.MAX_IMPORT_ROWS if update_compatible else data_io.MAX_EXPORT_ROWS,
    )
    payload, media = data_io.encode_table(
        dataset, format_name=format_name,
        rows=records, template=False, fields=headers,
        update_compatible=update_compatible,
    )
    return Response(
        content=payload, media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{model_name}-{"update" if update_compatible else "export"}.{format_name}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/data-models/{model_name}/import")
async def import_model(
    model_name: str, request: Request, actor: Actor, db: Db,
    dry_run: bool = True, expected_sha256: str | None = None,
    preview_id: str | None = None,
) -> dict:
    """Preview before applying one atomic, Store-owned spreadsheet update."""
    dataset = authorize(actor, model_name, write=True)
    context = current_context()
    if expected_sha256 is not None and not re.fullmatch(
        r"[a-f0-9]{64}", expected_sha256,
    ):
        raise security.SecurityRejected("invalid_import_request", 422)
    size = request.headers.get("content-length")
    if size is not None and (
        not size.isdecimal() or int(size) > data_io.MAX_BYTES
    ):
        raise security.SecurityRejected("invalid_import_file", 413)
    raw = await request.body()
    if len(raw) > data_io.MAX_BYTES:
        raise security.SecurityRejected("invalid_import_file", 413)
    if dry_run:
        # A preview authorizes this exact file and database snapshot for
        # this signed Staff, current Store, context version and browser session.
        outcome = await data_io.preview_or_apply(
            db, dataset=dataset, raw=raw,
            store_id=context.current_store_id, dry_run=True,
            expected_sha256=None,
        )
        receipt = await previews.issue_preview(
            db, context=context, model_name=dataset.name, result=outcome,
        )
        receipt.pop("snapshot_sha256", None)
        return receipt
    if preview_id is None or expected_sha256 is None:
        raise security.SecurityRejected("import_preview_required", 409)
    locked_receipt = await previews.claim_preview(
        db, context=context, model_name=dataset.name,
        receipt_id=preview_id, expected_sha256=expected_sha256,
    )
    result = await data_io.preview_or_apply(
        db, dataset=dataset, raw=raw,
        store_id=context.current_store_id,
        dry_run=False, expected_sha256=expected_sha256,
        preview_receipt=locked_receipt,
    )
    result.pop("snapshot_sha256", None)
    return result
