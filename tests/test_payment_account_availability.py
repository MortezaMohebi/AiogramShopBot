"""Test the dashboard's Telegram IRR availability contract without providers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from dashboard import shop_store_commerce_api as api
from services.shop_admin_security import SecurityRejected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured", "multiplier", "available"),
    [(False, 100, False), (True, 0, False), (True, 100, True)],
)
async def test_telegram_fiat_status_keeps_existing_accounts(
    monkeypatch, configured, multiplier, available,
):
    """Separate rail readiness from the stored state of a payment account."""
    store_id = uuid4()
    items = [{"rail_type": "telegram_fiat", "state": "active"}]
    monkeypatch.setattr(api, "service_enabled", lambda _key: configured)
    monkeypatch.setattr(api.config, "TELEGRAM_IRR_MINOR_MULTIPLIER", multiplier)
    monkeypatch.setattr(api.accounts, "list_accounts", AsyncMock(
        return_value={"store_id": str(store_id), "items": items},
    ))
    result = await api.list_payment_accounts(
        store_id, SimpleNamespace(role="superadmin"), None,
    )
    assert result == {
        "store_id": str(store_id),
        "items": items,
        "telegram_fiat_enabled": available,
    }


@pytest.mark.asyncio
async def test_unavailable_telegram_fiat_cannot_be_added_by_direct_request(monkeypatch):
    """Reject stale or forged requests before any payment account mutation."""
    monkeypatch.setattr(api, "service_enabled", lambda _key: False)
    stage = AsyncMock()
    monkeypatch.setattr(api.accounts, "create_account", stage)
    payload = api.PaymentAccountCreate(
        platform="telegram", rail_type="telegram_fiat", name="Test",
        token="test-only-provider-token", current_password="test-only",
    )
    with pytest.raises(SecurityRejected) as rejected:
        await api.create_payment_account(
            uuid4(), payload, SimpleNamespace(id=1, role="superadmin"), None,
        )
    assert rejected.value.code == "telegram_fiat_unavailable"
    stage.assert_not_awaited()
