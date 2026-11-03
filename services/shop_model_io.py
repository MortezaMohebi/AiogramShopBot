"""Reusable CSV/XLSX template, import-preview, commit and export service.

Every model's allowed columns come from the shared ModelRegistry. All imports
are atomic, Store-scoped, idempotent by explicit external_ref/SKU, and reject
formula cells or unknown headers. No customer is linked by phone/name, no
identity consent is inferred, and historic financial entries are untouched.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.shop_content import Product, ShopCategory
from models.shop_checkout import ShopCartItem, ShopOrderLine
from models.shop_store_commerce import ShopStoreCustomer
from models.shop_uom import ShopUom, default_unit_id
from services import shop_admin_security as security
from services.shop_model_registry import Dataset, Field
from services.shop_store_context import StoreContext
from services.shop_uom import validate_product_units

MAX_BYTES = 8 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024
MAX_IMPORT_ROWS = 1_000
MAX_EXPORT_ROWS = 5_000
REF_PATTERN = re.compile(r"^[a-zA-Z0-9_.:\-]{1,80}$")


@dataclass(frozen=True, slots=True)
class RowPlan:
    """A parsed, validated pending create/update with no side effects."""

    number: int
    action: str
    record: Product | ShopStoreCustomer | None
    values: dict[str, Any]


def _safe_cell(value: Any) -> Any:
    """Prevent spreadsheet-formula execution and CSV injection on export."""
    if isinstance(value, str) and value.lstrip().startswith(
        ("=", "+", "-", "@", "\t", "\r"),
    ):
        return "'" + value
    return value if value is not None else ""


def _headers(dataset: Dataset, *, template: bool) -> list[str]:
    """Reuse the registry's exposure rules, never arbitrary ORM columns."""
    if template:
        return [field.key for field in dataset.fields if field.importable]
    return [field.key for field in dataset.fields if field.exportable]


def encode_table(
    dataset: Dataset, *, format_name: str, rows: list[dict],
    template: bool,
) -> tuple[bytes, str]:
    """Encode one spreadsheet format with identical header contracts."""
    if format_name not in {"csv", "xlsx"}:
        raise security.SecurityRejected("unsupported_data_format", 422)
    headers = _headers(dataset, template=template)
    if format_name == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(headers)
        for record in rows:
            writer.writerow([_safe_cell(record.get(key)) for key in headers])
        return (
            b"\xef\xbb\xbf" + output.getvalue().encode("utf-8"),
            "text/csv; charset=utf-8",
        )

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Data"
    sheet.append(headers)
    sheet.freeze_panes = "A2"
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="1F365B")
        cell.font = Font(color="FFFFFF", bold=True)
    for column, key in enumerate(headers, start=1):
        field = dataset.field(
            key, intent="import" if template else "export",
        )
        sheet.column_dimensions[cell_column(column)].width = min(
            max(len(field.title) + 3, len(key) + 4, 15), 40,
        )
    for record in rows:
        sheet.append([
            _safe_cell(record.get(key)) for key in headers
        ])
    if template:
        help_sheet = workbook.create_sheet("Guide")
        help_sheet.append(["Column", "Label", "Required", "Value Type"])
        for field in dataset.fields:
            if field.importable:
                help_sheet.append([
                    field.key, field.title,
                    "Yes" if field.required else "No", field.kind,
                ])
        help_sheet.column_dimensions["A"].width = 30
        help_sheet.column_dimensions["B"].width = 34
        help_sheet.column_dimensions["C"].width = 14
        help_sheet.column_dimensions["D"].width = 20
        help_sheet.freeze_panes = "A2"
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return (
        output.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def cell_column(index: int) -> str:
    """Convert a positive 1-based column to spreadsheet notation."""
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)


def decode_table(
    dataset: Dataset, *, raw: bytes, format_name: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Decode one strictly bounded CSV/XLSX sheet without evaluating formulas."""
    if (
        format_name not in {"csv", "xlsx"}
        or not raw or len(raw) > MAX_BYTES
    ):
        raise security.SecurityRejected("invalid_import_file", 422)

    if format_name == "csv":
        try:
            decoded = raw.decode("utf-8-sig", errors="strict")
            stream = csv.reader(io.StringIO(decoded, newline=""))
            lines = iter(stream)
            headers = [str(item).strip() for item in next(lines)]
            values = [list(row) for row in lines]
        except (UnicodeError, csv.Error, StopIteration):
            raise security.SecurityRejected("invalid_import_file", 422) from None
    else:
        try:
            with ZipFile(io.BytesIO(raw)) as archive:
                expanded = sum(part.file_size for part in archive.infolist())
                if (
                    len(archive.infolist()) > 500
                    or expanded > MAX_UNPACKED
                    or any(part.file_size > MAX_UNPACKED for part in archive.infolist())
                ):
                    raise security.SecurityRejected("invalid_import_file", 422)
            workbook = load_workbook(
                io.BytesIO(raw), read_only=True, data_only=False,
                keep_links=False,
            )
            try:
                sheet = workbook["Data"] if "Data" in workbook else workbook.active
                iterator = sheet.iter_rows(values_only=False)
                header_cells = next(iterator)
                headers = [
                    str(cell.value).strip() if cell.value is not None else ""
                    for cell in header_cells
                ]
                values = []
                for index, line in enumerate(iterator):
                    if index >= MAX_IMPORT_ROWS:
                        raise security.SecurityRejected("import_too_many_rows", 422)
                    if any(cell.data_type == "f" for cell in line):
                        raise security.SecurityRejected("import_formula_not_allowed", 422)
                    values.append([cell.value for cell in line])
            finally:
                workbook.close()
        except (BadZipFile, KeyError, StopIteration, OSError, ValueError):
            raise security.SecurityRejected("invalid_import_file", 422) from None
    accepted = {field.key for field in dataset.fields if field.importable}
    if (
        not headers or len(headers) > 40
        or len(set(headers)) != len(headers)
        or any(header not in accepted for header in headers)
        or len(values) > MAX_IMPORT_ROWS
    ):
        raise security.SecurityRejected("invalid_import_columns", 422)
    result = []
    for index, line in enumerate(values, start=2):
        if len(line) > len(headers):
            raise security.SecurityRejected("invalid_import_columns", 422)
        data = dict(zip(headers, line, strict=False))
        if not any(value is not None and str(value).strip() for value in data.values()):
            continue
        result.append({"row": index, "values": data})
    return headers, result


def _parse(field: Field, raw: Any) -> Any:
    """Validate one import cell using the common ModelRegistry field type."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if field.key in {"external_ref", "sku", "uom_code", "purchase_uom_code"}:
        if not isinstance(raw, str):
            raw = str(raw)
    return field.parse(raw)


async def _plan_product(
    db: AsyncSession, *, store_id: str, line: dict[str, Any],
    index: int,
) -> RowPlan:
    """Find Products by explicit reference/SKU, never name or bot identity."""
    external_ref = line.get("external_ref")
    sku = line.get("sku")
    if external_ref and not REF_PATTERN.fullmatch(external_ref):
        raise security.SecurityRejected("invalid_external_reference", 422)
    if not sku and not external_ref:
        raise security.SecurityRejected("import_identity_required", 422)

    existing = None
    if external_ref:
        existing = await db.scalar(select(Product).where(
            Product.store_id == store_id,
            Product.external_ref == external_ref,
        ).with_for_update())
    if sku:
        matches_sku = await db.scalar(select(Product).where(
            Product.store_id == store_id, Product.sku == sku,
        ).with_for_update())
        if matches_sku is not None:
            if existing is not None and existing.id != matches_sku.id:
                raise security.SecurityRejected("import_identity_conflict", 409)
            if (
                existing is None and external_ref
                and matches_sku.external_ref not in (None, external_ref)
            ):
                raise security.SecurityRejected("import_identity_conflict", 409)
            existing = matches_sku
    if existing is not None and external_ref and existing.external_ref not in (
        None, external_ref,
    ):
        raise security.SecurityRejected("import_identity_conflict", 409)

    values = {
        key: value for key, value in line.items() if value is not None
    }
    if existing is None:
        for field in ("name", "price_irr"):
            if values.get(field) in (None, ""):
                raise security.SecurityRejected("import_required_field", 422)
    if "price_irr" in values and not 0 <= values["price_irr"] <= 9_999_999_999_999_999:
        raise security.SecurityRejected("invalid_import_value", 422)
    if "stock_quantity" in values and not 0 <= values["stock_quantity"] <= 100_000_000:
        raise security.SecurityRejected("invalid_import_value", 422)
    if existing is not None and "stock_quantity" in values and (
        values["stock_quantity"] != existing.stock_quantity
    ):
        # Existing stock requires a separate audited adjustment ledger;
        # silent replacement from a spreadsheet would lose inventory history.
        raise security.SecurityRejected("import_stock_adjustment_required", 409)
    if values.get("is_published") is True:
        raise security.SecurityRejected("import_publish_requires_review", 409)
    if "price_stars" in values and values["price_stars"] <= 0:
        raise security.SecurityRejected("invalid_import_value", 422)
    ptype = values.get(
        "product_type", existing.product_type if existing else "physical",
    )
    if ptype not in {"physical", "digital"}:
        raise security.SecurityRejected("invalid_import_value", 422)
    requires_shipping = values.get(
        "requires_shipping", existing.requires_shipping if existing else True,
    )
    if ptype == "digital" and requires_shipping:
        raise security.SecurityRejected("invalid_import_value", 422)
    if "category_id" in values:
        category = await db.get(ShopCategory, values["category_id"])
        if category is None or category.store_id != store_id:
            raise security.SecurityRejected("invalid_import_value", 422)
    uom = existing.uom_id if existing else default_unit_id(store_id)
    purchase_uom = existing.purchase_uom_id if existing else None
    if values.get("uom_code"):
        unit = await db.scalar(select(ShopUom).where(
            ShopUom.store_id == store_id,
            ShopUom.code == values["uom_code"],
        ))
        if unit is None:
            raise security.SecurityRejected("uom_not_available", 422)
        uom = unit.id
    if values.get("purchase_uom_code"):
        purchase = await db.scalar(select(ShopUom).where(
            ShopUom.store_id == store_id,
            ShopUom.code == values["purchase_uom_code"],
        ))
        if purchase is None:
            raise security.SecurityRejected("uom_not_available", 422)
        purchase_uom = purchase.id
    uom, purchase_uom = await validate_product_units(
        db, store_id=store_id,
        uom_id=uom, purchase_uom_id=purchase_uom,
    )
    if existing is not None and uom != existing.uom_id:
        in_cart = await db.scalar(select(ShopCartItem.id).where(
            ShopCartItem.product_id == existing.id,
        ).limit(1))
        in_order = await db.scalar(select(ShopOrderLine.id).where(
            ShopOrderLine.product_id == existing.id,
        ).limit(1))
        if existing.stock_quantity or in_cart is not None or in_order is not None:
            raise security.SecurityRejected("uom_locked", 409)
    values["uom_id"] = uom
    values["purchase_uom_id"] = purchase_uom
    values["price"] = values.pop("price_irr", existing.price if existing else 0)
    values.pop("uom_code", None)
    values.pop("purchase_uom_code", None)
    if existing is None:
        values.setdefault(
            "sku", "AUTO-" + hashlib.sha256(
                f"{store_id}:{external_ref}".encode("utf-8"),
            ).hexdigest()[:18].upper(),
        )
        values.setdefault("description", "")
        values.setdefault("stock_quantity", 0)
        # No new Product is bulk-published by importing a spreadsheet.
        if values.get("is_published") is True:
            raise security.SecurityRejected("import_publish_requires_review", 409)
        values["is_published"] = False
    return RowPlan(
        number=index,
        action="update" if existing is not None else "create",
        record=existing, values=values,
    )


async def _plan_customer(
    db: AsyncSession, *, store_id: str, line: dict[str, Any],
    index: int,
) -> RowPlan:
    """Never merge customers from matching names, phones or messenger IDs."""
    key = line.get("external_ref")
    if not key or not REF_PATTERN.fullmatch(key):
        raise security.SecurityRejected("import_identity_required", 422)
    record = await db.scalar(select(ShopStoreCustomer).where(
        ShopStoreCustomer.store_id == store_id,
        ShopStoreCustomer.external_ref == key,
    ).with_for_update())
    return RowPlan(
        number=index,
        action="update" if record is not None else "create",
        record=record,
        values={key: value for key, value in line.items() if value is not None},
    )


async def preview_or_apply(
    db: AsyncSession, *, dataset: Dataset, raw: bytes,
    format_name: str, store_id: str, dry_run: bool,
    expected_sha256: str | None,
) -> dict:
    """Preview or atomically upsert explicit models within the current Store."""
    if dataset.name not in {"products", "customers"}:
        raise security.SecurityRejected("model_import_not_supported", 405)
    if type(dry_run) is not bool:
        raise security.SecurityRejected("invalid_import_request", 422)
    digest = hashlib.sha256(raw).hexdigest()
    if not dry_run and expected_sha256 != digest:
        raise security.SecurityRejected("import_preview_required", 409)
    _, raw_rows = decode_table(dataset, raw=raw, format_name=format_name)
    if not raw_rows:
        raise security.SecurityRejected("import_empty_file", 422)
    # One duplicate reference in a file could otherwise update one record
    # more than once with conflicting values.
    seen_keys: set[str] = set()
    plans = []
    for record in raw_rows:
        values: dict[str, Any] = {}
        for name, value in record["values"].items():
            field = dataset.field(name, intent="import")
            values[name] = _parse(field, value)
        identity = values.get("external_ref") or values.get("sku")
        if identity:
            if identity in seen_keys:
                raise security.SecurityRejected("import_duplicate_key", 409)
            seen_keys.add(identity)
        if dataset.name == "products":
            plan = await _plan_product(
                db, store_id=store_id, line=values, index=record["row"],
            )
        else:
            plan = await _plan_customer(
                db, store_id=store_id, line=values, index=record["row"],
            )
        plans.append(plan)
    summary = {
        "model": dataset.name, "rows": len(plans),
        "creates": sum(row.action == "create" for row in plans),
        "updates": sum(row.action == "update" for row in plans),
        "sha256": digest,
        "preview": [{
            "row": row.number, "action": row.action,
        } for row in plans[:30]],
    }
    if dry_run:
        return {**summary, "committed": False}

    try:
        for plan in plans:
            if plan.record is None:
                if dataset.name == "products":
                    item = Product(
                        store_id=store_id,
                        **plan.values,
                    )
                else:
                    item = ShopStoreCustomer(
                        store_id=store_id,
                        **plan.values,
                    )
                db.add(item)
            else:
                for name, value in plan.values.items():
                    if name in {"is_published", "stock_quantity"} and (
                        dataset.name == "products"
                    ):
                        # Bulk publishing/stock overwrite are out of scope.
                        continue
                    setattr(plan.record, name, value)
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise security.SecurityRejected("import_conflict", 409) from None
    return {**summary, "committed": True}
