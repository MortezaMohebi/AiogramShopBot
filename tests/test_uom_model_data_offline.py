"""Deferred offline contracts for the generic model/UoM/data exchange layer.

No PostgreSQL, Telegram, Bale, Redis, remote provider or browser session
is used in these tests. They must be executed after QA dependencies exist.
"""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from types import SimpleNamespace

import pytest

from models.shop_uom import ShopUom, convert_quantity, default_unit_id
from services.shop_admin_security import SecurityRejected
from services.shop_model_io import decode_table, encode_table
from services.shop_model_registry import (
    CUSTOMER, ORDER, PRODUCT, escape_like, filtered_clause, get_dataset,
)
from services.shop_store_context import (
    AuthorizedStore, StoreContext, bind_context, current_context,
)


def unit(*, code: str, num: int, den: int, store: str = "store-a") -> ShopUom:
    """Build an in-memory unit without opening a database connection."""
    return ShopUom(
        id=code, store_id=store, category_id="count",
        code=code, name=code, symbol=code,
        ratio_num=num, ratio_den=den,
        rounding=Decimal("1"),
        is_reference=code == "piece",
    )


def test_uom_exact_rational_conversion() -> None:
    """One dozen equals exactly twelve pieces with no float rounding."""
    package = unit(code="dozen", num=12, den=1)
    piece = unit(code="piece", num=1, den=1)
    assert convert_quantity(Decimal("3"), package, piece) == Decimal("36")
    assert convert_quantity(Decimal("24"), piece, package) == Decimal("2")


def test_uom_rejects_nonrepresentable_and_cross_store() -> None:
    """Quantities cannot be rounded or converted across merchant Stores."""
    piece = unit(code="piece", num=1, den=1)
    dozen = unit(code="dozen", num=12, den=1)
    with pytest.raises(ValueError, match="precision"):
        convert_quantity(Decimal("1"), piece, dozen)
    with pytest.raises(ValueError, match="Store/category"):
        convert_quantity(1, piece, unit(
            code="dozen", num=12, den=1, store="store-b",
        ))


def test_reference_uom_id_is_stable_per_store() -> None:
    """The same store yields one ID while separate Stores cannot share one."""
    assert default_unit_id("store-a") == default_unit_id("store-a")
    assert default_unit_id("store-a") != default_unit_id("store-b")


def test_dataset_registry_exposes_only_explicit_fields() -> None:
    """Unknown ORM models or secret attributes never become queryable."""
    assert get_dataset("products") is PRODUCT
    assert get_dataset("customers") is CUSTOMER
    assert get_dataset("orders") is ORDER
    with pytest.raises(SecurityRejected):
        get_dataset("shop_admin_profiles")
    with pytest.raises(SecurityRejected):
        PRODUCT.field("password_hash", intent="search")
    with pytest.raises(SecurityRejected):
        PRODUCT.field("uom_code", intent="import_nonexistent")


def test_literal_sql_wildcards_are_escaped() -> None:
    """User percent/underscore never expand the search unintentionally."""
    assert escape_like(r"A%_B") == r"A\%\_B"
    statement = filtered_clause(
        PRODUCT.field("name", intent="search"), "contains", "A%_B",
    )
    assert "ilike" in str(statement).lower() or "lower" in str(statement).lower()


def test_typed_filter_rejects_bad_operators() -> None:
    """Boolean and numeric field operators remain strongly allowlisted."""
    with pytest.raises(SecurityRejected):
        filtered_clause(
            PRODUCT.field("price_irr", intent="search"),
            "contains", "10",
        )
    with pytest.raises(SecurityRejected):
        filtered_clause(
            PRODUCT.field("is_published", intent="search"),
            "eq", "maybe",
        )
    with pytest.raises(SecurityRejected):
        filtered_clause(
            PRODUCT.field("name", intent="search"),
            "in", ["a"] * 30,
        )


def test_csv_template_uses_registry_and_utf8_bom() -> None:
    """CSV imports exactly the registry's import field set."""
    payload, mime = encode_table(
        PRODUCT, format_name="csv", rows=[], template=True,
    )
    assert payload.startswith(b"\xef\xbb\xbf")
    assert mime.startswith("text/csv")
    header, records = decode_table(
        PRODUCT, raw=payload, format_name="csv",
    )
    assert "uom_code" in header
    assert "external_ref" in header
    assert "store_id" not in header
    assert records == []


def test_xlsx_template_round_trip() -> None:
    """Workbook and CSV follow identical import column declarations."""
    payload, mime = encode_table(
        CUSTOMER, format_name="xlsx", rows=[], template=True,
    )
    assert mime.endswith("spreadsheetml.sheet")
    headers, rows = decode_table(
        CUSTOMER, raw=payload, format_name="xlsx",
    )
    assert "external_ref" in headers
    assert "display_name" in headers
    assert "store_id" not in headers
    assert rows == []


def test_csv_formula_injection_is_escaped() -> None:
    """External names cannot become executable spreadsheet formulas."""
    payload, _ = encode_table(
        CUSTOMER, format_name="csv", template=False, rows=[{
            "id": 7, "external_ref": "customer-7",
            "display_name": "=HYPERLINK(foo)", "phone": "@SUM(A1:A5)",
        }],
    )
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    fields = rows[0]
    assert rows[1][fields.index("display_name")].startswith("'=")
    assert rows[1][fields.index("phone")].startswith("'@")


def test_import_rejects_unknown_and_duplicate_headers() -> None:
    """Any unmapped field is an error, not a writable ORM attribute."""
    for header in ("name,password_hash", "name,name"):
        with pytest.raises(SecurityRejected):
            decode_table(
                PRODUCT,
                raw=(header + "\nABC,DEF\n").encode("utf-8"),
                format_name="csv",
            )


def test_store_context_is_request_bound_and_authorized() -> None:
    """One current Store handles writes even when two Stores are selected."""
    a = AuthorizedStore(
        id="a", slug="a", name="A", state="active",
        access_level="manager",
    )
    b = AuthorizedStore(
        id="b", slug="b", name="B", state="active",
        access_level="editor",
    )
    context = StoreContext(
        staff_id=1, session_id="session", allowed_stores=(a, b),
        active_store_ids=("a", "b"),
        current_store_id="a", default_store_id="a", version=1,
    )
    assert current_context() is None
    with bind_context(context):
        assert current_context() is context
        context.require("b")
        context.require("a", write=True)
        with pytest.raises(SecurityRejected):
            context.require("b", write=True)
        with pytest.raises(SecurityRejected):
            context.require("missing")
    assert current_context() is None
