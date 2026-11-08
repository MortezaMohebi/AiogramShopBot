"""Deferred QA for single-use Store-scoped spreadsheet preview receipts.

All tests are offline; no PostgreSQL connection, browser or provider token
is required. The database-specific atomicity tests still require PostgreSQL.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from models.shop_model_import import ShopModelImportPreview
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_admin_security import SecurityRejected
from services.shop_import_preview import claim_preview, issue_preview
from services.shop_model_io import RowPlan, _snapshot_digest
from services.shop_store_context import AuthorizedStore, StoreContext

STORE_A = str(uuid4())
STORE_B = str(uuid4())
SESSION_A = str(uuid4())
STAFF_ID = 42
HASH = "b" * 64
SNAPSHOT_HASH = "c" * 64


class FakeDatabase:
    """Minimal read/commit adapter for pure preview policy acceptance tests."""

    def __init__(self, receipt: ShopModelImportPreview | None = None) -> None:
        """Optionally expose exactly one read-only receipt."""
        self.receipt = receipt
        self.commits = 0

    def add(self, value: ShopModelImportPreview) -> None:
        """Capture the proposed receipt without starting a SQL connection."""
        self.receipt = value

    async def commit(self) -> None:
        """Count local transaction commits with no persistent side effects."""
        self.commits += 1

    async def scalar(self, query) -> ShopModelImportPreview | None:
        """Return a synthetic locked-receipt result."""
        return self.receipt


def context() -> StoreContext:
    """Build an allowed two-Store session with one current write Store."""
    stores = (
        AuthorizedStore(
            id=STORE_A, slug="a", name="Store A",
            state="active", access_level="editor",
        ),
        AuthorizedStore(
            id=STORE_B, slug="b", name="Store B",
            state="active", access_level="editor",
        ),
    )
    return StoreContext(
        staff_id=STAFF_ID, session_id=SESSION_A,
        allowed_stores=stores,
        active_store_ids=(STORE_A, STORE_B),
        current_store_id=STORE_A,
        default_store_id=STORE_A, version=3,
    )


def synthetic_receipt() -> ShopModelImportPreview:
    """Create a fresh preview bound to one exact user/session/store/snapshot."""
    ctx = context()
    return ShopModelImportPreview(
        id=str(uuid4()), staff_id=ctx.staff_id,
        session_id=ctx.session_id, store_id=ctx.current_store_id,
        store_context_version=ctx.version,
        dataset_name="products",
        file_sha256=HASH, snapshot_sha256=SNAPSHOT_HASH,
        rows=3, creates=1, updates=2,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )


def test_issue_returns_one_receipt_without_file_contents() -> None:
    """Only the digest/counts and opaque proof remain in the preview ledger."""

    async def scenario() -> None:
        db = FakeDatabase()
        result = await issue_preview(
            db, context=context(), model_name="products",
            result={
                "sha256": HASH, "snapshot_sha256": SNAPSHOT_HASH,
                "rows": 3, "creates": 1, "updates": 2,
                "preview": [], "committed": False,
            },
        )
        assert db.commits == 1
        assert db.receipt is not None
        assert result["preview_id"] == db.receipt.id
        assert db.receipt.file_sha256 == HASH
        assert db.receipt.snapshot_sha256 == SNAPSHOT_HASH
        assert db.receipt.store_id == STORE_A
        assert db.receipt.session_id == SESSION_A

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "change",
    (
        {"staff_id": 999},
        {"session_id": str(uuid4())},
        {"current_store_id": STORE_B},
        {"version": 4},
    ),
)
def test_preview_cannot_cross_user_device_store_or_context(change: dict) -> None:
    """A matching CSV hash cannot authorize another Store's current session."""

    async def scenario() -> None:
        db = FakeDatabase(synthetic_receipt())
        with pytest.raises(SecurityRejected) as failure:
            await claim_preview(
                db, context=replace(context(), **change),
                model_name="products", receipt_id=db.receipt.id,
                expected_sha256=HASH,
            )
        assert failure.value.code == "import_preview_required"

    asyncio.run(scenario())


def test_valid_single_use_receipt_and_replay_rejection() -> None:
    """The same receipt must fail after consumption, even with matching hash."""

    async def scenario() -> None:
        db = FakeDatabase(synthetic_receipt())
        selected = await claim_preview(
            db, context=context(), model_name="products",
            receipt_id=db.receipt.id, expected_sha256=HASH,
        )
        assert selected is db.receipt
        selected.consumed_at = datetime.now(timezone.utc)
        with pytest.raises(SecurityRejected):
            await claim_preview(
                db, context=context(), model_name="products",
                receipt_id=db.receipt.id, expected_sha256=HASH,
            )

    asyncio.run(scenario())


def test_stale_preview_and_wrong_file_or_model_rejected() -> None:
    """Expired authorizations cannot be replayed or repurposed."""

    async def scenario() -> None:
        db = FakeDatabase(synthetic_receipt())
        for name, digest in (
            ("customers", HASH), ("products", "d" * 64),
        ):
            with pytest.raises(SecurityRejected):
                await claim_preview(
                    db, context=context(), model_name=name,
                    receipt_id=db.receipt.id, expected_sha256=digest,
                )
        db.receipt.expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        )
        with pytest.raises(SecurityRejected):
            await claim_preview(
                db, context=context(), model_name="products",
                receipt_id=db.receipt.id, expected_sha256=HASH,
            )

    asyncio.run(scenario())


def test_row_snapshot_detects_intervening_customer_modification() -> None:
    """The identical file is insufficient if the database changed meanwhile."""
    customer = ShopStoreCustomer(
        id=17, store_id=STORE_A, external_ref="customer-17",
        display_name="Before", phone="",
    )
    plan = RowPlan(
        number=2, action="update", record=customer,
        values={"display_name": "New"},
    )
    original = _snapshot_digest([plan])
    customer.display_name = "Modified by another session"
    assert original != _snapshot_digest([plan])
    new_plan = RowPlan(
        number=2, action="create", record=None,
        values={"external_ref": "customer-17"},
    )
    assert original != _snapshot_digest([new_plan])
