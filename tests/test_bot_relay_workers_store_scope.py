"""Verify Relay choices through the signed, revocable multi-Store boundary."""

from uuid import uuid4

import pytest

from models.shop_admin_control import AdminProfile
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot
from models.shop_relay_pool import ShopBotRelayRoute, ShopRelayWorker
from models.shop_staff import ShopStaff
from tests.test_campaign_admin_store_scope import (  # noqa: F401
    BOT_A, BOT_B, STORE_A, STORE_B, campaign_app,
)


@pytest.mark.asyncio
async def test_bot_relay_choices_work_in_multiple_stores_without_foreign_counts(
    campaign_app,
):
    """Shared infrastructure metadata never leaks another Store's route count."""
    db = campaign_app.db
    db.get(ShopStaff, 7).role = "superadmin"
    db.add(AdminProfile(staff_id=7, mfa_secret="synthetic-enrolled-profile"))
    worker_id, hidden_bot = str(uuid4()), str(uuid4())
    db.add(ShopRelayWorker(
        id=worker_id, slug="qa-worker", name="QA Worker",
        origin="https://qa.example.workers.dev", status="draft",
    ))
    db.add(ShopBot(
        id=hidden_bot, store_id=DEFAULT_STORE_ID, slug="hidden-bot",
        name="Hidden", platform="telegram", runtime_owner="registry",
    ))
    db.flush()
    for bot_id in (BOT_A, BOT_B, hidden_bot):
        db.add(ShopBotRelayRoute(
            bot_id=bot_id, worker_id=worker_id, priority=1, status="staged",
        ))
    db.commit()
    response = await campaign_app.request(
        "GET", f"/bot-registry/{BOT_A}/relay-workers",
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["bot_count"] == 1
    assert not any(
        key in str(response.json()) for key in (hidden_bot, "ciphertext", "secret")
    )
    denied = await campaign_app.request(
        "GET", f"/bot-registry/{hidden_bot}/relay-workers",
    )
    assert denied.status_code == 404
    assert denied.json()["detail"] == "bot_not_found"


@pytest.mark.asyncio
async def test_bot_relay_choices_reject_staff_without_bot_permission(campaign_app):
    """A valid marketing session does not acquire infrastructure permissions."""
    response = await campaign_app.request(
        "GET", f"/bot-registry/{BOT_A}/relay-workers",
    )
    assert response.status_code == 403
