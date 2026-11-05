"""Keep authenticated Runtime routing before legacy at-most-once receipts."""

from contextlib import asynccontextmanager
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import config
from channels.contracts import Platform
from models.shop_delivery import ShopInboundUpdate
from services.shop_runtime import ingress, sessions
from tests.test_action_security import buyer as buyer, db as db
from tests.test_runtime_adapters import message
from tests.test_runtime_sessions import setup_runtime


def use_database(monkeypatch, db):
    """Give the receiver a disposable real database with no external services."""

    @asynccontextmanager
    async def database():
        """Leave transaction ownership to the called service."""
        yield db

    monkeypatch.setattr(ingress, "session_maker", database)


@pytest.mark.asyncio
async def test_runtime_off_returns_to_legacy_without_database_or_provider(monkeypatch):
    """Default flags only read durable ownership; they cannot enroll or send."""
    monkeypatch.setattr(config, "SHOP_WORKFLOW_RUNTIME_ENABLED", False)
    use_database(monkeypatch, SimpleNamespace(scalar=AsyncMock(return_value=None)))
    assert await ingress.try_ingress(None, message(text="/wholesale")) == {
        "handled": False
    }
    assert await ingress.try_legacy_ingress(
        Platform.TELEGRAM, message(text="/wholesale")
    ) == {"handled": False}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag", ["SHOP_WORKFLOW_RUNTIME_ENABLED", "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH"]
)
async def test_disabled_runtime_retains_durable_duplicate_ownership(
    buyer, monkeypatch, flag
):
    """Disabling Runtime hands only new update IDs to legacy handlers."""
    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    use_database(monkeypatch, db)
    await ingress.try_ingress(principal.bot, message(text="/wholesale"))
    monkeypatch.setattr(config, flag, flag == "SHOP_WORKFLOW_RUNTIME_KILL_SWITCH")
    for route in (
        lambda payload: ingress.try_ingress(principal.bot, payload),
        lambda payload: ingress.try_legacy_ingress(Platform.TELEGRAM, payload),
    ):
        replay = await route(message(text="/wholesale"))
        assert replay == {"handled": True, "duplicate": True, "status": "processed"}
        assert await route(message(text="Alice") | {"update_id": 8}) == {
            "handled": False
        }


@pytest.mark.asyncio
async def test_financial_envelopes_bypass_runtime_before_database(monkeypatch):
    """Already issued invoices remain reachable with Runtime fully enabled."""
    monkeypatch.setattr(config, "SHOP_WORKFLOW_RUNTIME_ENABLED", True)
    monkeypatch.setattr(
        ingress,
        "session_maker",
        lambda: pytest.fail("Payment bypass must precede Runtime DB work"),
    )
    for payload in [
        {"update_id": 2, "pre_checkout_query": {}},
        message(successful_payment={}),
    ]:
        assert await ingress.try_ingress(None, payload) == {"handled": False}


@pytest.mark.asyncio
async def test_authenticated_ingress_durably_starts_and_deduplicates_run(
    buyer, monkeypatch
):
    """Fake-provider input enters only its authenticated Bot/customer workflow."""
    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    use_database(monkeypatch, db)
    first = await ingress.try_ingress(principal.bot, message(text="/wholesale"))
    assert first["handled"] and first["status"] == "waiting_input"
    again = await ingress.try_ingress(principal.bot, message(text="/wholesale"))
    assert again["handled"] and again["duplicate"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["needs_review", "processing", "processed"])
async def test_preexisting_legacy_receipt_never_becomes_new_runtime_input(
    buyer, monkeypatch, state
):
    """Enabling Runtime cannot replay a legacy receipt quarantined before rollout."""
    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    db.add(
        ShopInboundUpdate(
            bot_id=principal.bot_id,
            platform="telegram",
            bot_fingerprint="a" * 64,
            update_id=7,
            status=state,
        )
    )
    await db.commit()
    use_database(monkeypatch, db)
    handler = AsyncMock(
        side_effect=AssertionError("Legacy receipt must remain quarantined")
    )
    monkeypatch.setattr(sessions, "handle", handler)
    result = await ingress.try_ingress(principal.bot, message(text="/wholesale"))
    assert result == {"handled": True, "status": "duplicate", "receipt_state": state}
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_ingress_obeys_live_customer_restriction_before_coordinator(
    buyer, monkeypatch
):
    """No verified input bypasses a current identity block."""
    from models.shop_content import ShopIdentity

    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    identity = await db.get(ShopIdentity, principal.identity_id)
    identity.is_blocked = True
    await db.commit()
    use_database(monkeypatch, db)
    handler = AsyncMock(
        side_effect=AssertionError("Blocked customer cannot enter Runtime")
    )
    monkeypatch.setattr(sessions, "handle", handler)
    result = await ingress.try_ingress(principal.bot, message(text="/wholesale"))
    assert result["handled"] and result["status"] == "blocked"
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_ingress_passes_upload_verifier_without_sending_inline(
    buyer, monkeypatch
):
    """The coordinator owns durable inbox acceptance before file verification."""
    db, principal = buyer
    await setup_runtime(db, principal, monkeypatch)
    use_database(monkeypatch, db)
    coordinator = AsyncMock(return_value={"handled": True, "status": "queued"})
    monkeypatch.setattr(sessions, "handle", coordinator)
    client = SimpleNamespace()
    result = await ingress.try_ingress(
        principal.bot,
        message(
            document={
                "file_id": "private_file",
                "file_size": 12,
                "mime_type": "application/pdf",
            }
        ),
        client=client,
    )
    assert result["status"] == "queued"
    event = coordinator.call_args.kwargs["event"]
    assert event.kind == "document" and event.text == ""
    assert callable(coordinator.call_args.kwargs["file_verifier"])


@pytest.mark.asyncio
async def test_supervisor_offers_runtime_before_old_claim_and_propagates_crash(
    monkeypatch,
):
    """A pre-inbox exception cannot be hidden by a committed legacy receipt."""
    import db as db_module

    monkeypatch.setattr(db_module, "engine", SimpleNamespace(), raising=False)
    supervisor = importlib.import_module("services.shop_multibot_supervisor")
    from tests.test_runtime_adapters import context

    manager = supervisor.MultiBotSupervisor(SimpleNamespace())
    manager._identity = AsyncMock(return_value=(context(), "fake-token", "webhook", 0))
    monkeypatch.setattr(
        supervisor,
        "claim_update",
        AsyncMock(side_effect=AssertionError("Runtime must precede legacy claim")),
    )
    runtime = AsyncMock(return_value={"handled": True, "status": "queued"})
    monkeypatch.setattr(supervisor, "try_ingress", runtime)
    assert (
        await manager._process(
            context().bot_id, update_id=7, payload=message(text="/wholesale")
        )
    )["status"] == "queued"
    runtime.side_effect = RuntimeError("crash before inbox commit")
    with pytest.raises(RuntimeError, match="crash before inbox"):
        await manager._process(
            context().bot_id, update_id=7, payload=message(text="/wholesale")
        )
    supervisor.claim_update.assert_not_called()
