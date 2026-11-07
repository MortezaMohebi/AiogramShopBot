"""Bulk catalog visibility changes preserve records and fail atomically."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from dashboard import next_api
from models.shop_content import Product, ShopCategory


class FakeSession:
    """Expose selected locked rows and track transaction commits."""

    def __init__(self, rows):
        """Keep the exact rows returned by a scoped SELECT."""
        self.rows = rows
        self.commits = 0

    async def execute(self, statement):
        """Return the configured result for a SELECT FOR UPDATE."""
        assert statement is not None
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))

    async def commit(self):
        """Count the single transaction boundary."""
        self.commits += 1


@pytest.mark.parametrize("model", [Product, ShopCategory])
@pytest.mark.asyncio
async def test_bulk_unpublish_preserves_rows_and_commits_once(monkeypatch, model):
    """Both catalog lists hide selected rows without deleting their history."""
    rows = [
        SimpleNamespace(id=3, store_id="store-a", is_published=True),
        SimpleNamespace(id=4, store_id="store-a", is_published=False),
    ]
    session = FakeSession(rows)
    member = SimpleNamespace(role="content")
    monkeypatch.setattr(next_api, "admin_store_context", lambda user: SimpleNamespace(
        active_store_ids=["store-a"],
    ))
    monkeypatch.setattr(next_api, "require_store_access", lambda scope, store_id, write: None)
    result = await next_api.bulk_unpublish_rows(model, [3, 4], member, session)
    assert result == {"selected": 2, "unpublished": 1}
    assert all(not row.is_published for row in rows)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_bulk_unpublish_rejects_missing_or_foreign_row_without_changes(monkeypatch):
    """A partial selection cannot mutate any other selected product."""
    row = SimpleNamespace(id=3, store_id="store-a", is_published=True)
    session = FakeSession([row])
    monkeypatch.setattr(next_api, "admin_store_context", lambda user: SimpleNamespace(
        active_store_ids=["store-a"],
    ))
    with pytest.raises(HTTPException) as error:
        await next_api.bulk_unpublish_rows(
            Product, [3, 99], SimpleNamespace(role="content"), session,
        )
    assert error.value.status_code == 404
    assert row.is_published is True
    assert session.commits == 0


@pytest.mark.asyncio
async def test_bulk_unpublish_checks_all_write_grants_before_mutating(monkeypatch):
    """One read-only store prevents the complete batch from changing."""
    rows = [
        SimpleNamespace(id=3, store_id="store-a", is_published=True),
        SimpleNamespace(id=4, store_id="store-b", is_published=True),
    ]
    session = FakeSession(rows)
    monkeypatch.setattr(next_api, "admin_store_context", lambda user: SimpleNamespace(
        active_store_ids=["store-a", "store-b"],
    ))

    def grant(scope, store_id, write):
        """Deny writes to the second store."""
        if store_id == "store-b":
            raise HTTPException(status_code=403, detail="permission_denied")

    monkeypatch.setattr(next_api, "require_store_access", grant)
    with pytest.raises(HTTPException) as error:
        await next_api.bulk_unpublish_rows(
            Product, [3, 4], SimpleNamespace(role="content"), session,
        )
    assert error.value.status_code == 403
    assert all(row.is_published for row in rows)
    assert session.commits == 0


def test_bulk_payload_rejects_duplicates_and_invalid_ids():
    """Clients cannot submit an empty, boolean or negative selection."""
    for ids in ([], [True], [0], [-1]):
        with pytest.raises(ValidationError):
            next_api.BulkUnpublishPayload(ids=ids)


@pytest.mark.asyncio
async def test_bulk_unpublish_rejects_duplicate_ids_before_query():
    """Repeated IDs cannot inflate counts or create partial results."""
    session = FakeSession([])
    with pytest.raises(HTTPException) as error:
        await next_api.bulk_unpublish_rows(
            Product, [3, 3], SimpleNamespace(role="content"), session,
        )
    assert error.value.status_code == 422
    assert session.commits == 0
