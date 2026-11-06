"""Action authorization is derived from live Store/Bot/customer records."""

from dataclasses import replace

import pytest
import pytest_asyncio

from channels.contracts import Platform
from models.shop_content import ShopIdentity
from models.shop_multibot import DEFAULT_STORE_ID, ShopBot, ShopStore
from models.shop_store_commerce import ShopStoreCustomer
from services.shop_actions.context import customer_principal, refresh_principal
from services.shop_actions.contracts import ActionRejected
from services.shop_bot_context import resolve_bot_context
from tests.test_shared_cart import db
from tests.schema_support import TEST_BOT_IDS, seed_customer


@pytest_asyncio.fixture
async def buyer(db):
    """Bind an existing identity without invoking enrollment or a real provider."""
    identity = seed_customer(db.session, "telegram", 101)
    (await db.get(ShopStoreCustomer, identity.customer_id)).display_name = "QA buyer"
    await db.commit()
    bot = await resolve_bot_context(
        db,
        authenticated_bot_id=identity.bot_id,
        authenticated_platform=Platform.TELEGRAM,
    )
    return db, await customer_principal(db, verified_bot=bot, platform_user_id=101)


@pytest.mark.asyncio
async def test_trusted_customer_context_has_no_credentials(buyer):
    """The actual identity's Store/Bot/customer grants determine the principal."""
    _, principal = buyer
    assert principal.store_id == DEFAULT_STORE_ID
    assert principal.platform == "telegram" and principal.platform_user_id == 101
    assert principal.actor_kind == "customer"
    assert "cart.write" in principal.scopes
    assert not hasattr(principal, "token")


@pytest.mark.asyncio
async def test_changed_customer_claim_is_rejected(buyer):
    """A stale/spoofed customer ID cannot borrow a different verified identity."""
    db, principal = buyer
    with pytest.raises(ActionRejected, match="action_identity_changed"):
        await refresh_principal(
            db, replace(principal, customer_id=principal.customer_id + 1)
        )


@pytest.mark.asyncio
async def test_wrong_platform_or_store_is_rejected(buyer):
    """Matching numeric IDs do not establish platform or tenant ownership."""
    db, principal = buyer
    for changed in (
        replace(principal, platform="bale"),
        replace(principal, store_id="00000000-0000-4000-8000-000000000999"),
    ):
        with pytest.raises(ActionRejected):
            await refresh_principal(db, changed)


@pytest.mark.asyncio
async def test_blocked_identity_is_rechecked_before_replay(buyer):
    """A previously issued principal never preserves a revoked identity grant."""
    db, principal = buyer
    identity = await db.get(ShopIdentity, principal.identity_id)
    identity.is_blocked = True
    await db.commit()
    with pytest.raises(ActionRejected, match="action_customer_unavailable"):
        await refresh_principal(db, principal)


@pytest.mark.asyncio
async def test_disabled_bot_is_rechecked(buyer):
    """Disabling a Bot invalidates existing Action context immediately."""
    db, principal = buyer
    bot = await db.get(ShopBot, principal.bot_id)
    bot.runtime_owner = "registry"
    bot.status = "disabled"
    await db.commit()
    with pytest.raises(ActionRejected, match="action_bot_unavailable"):
        await refresh_principal(db, principal)


@pytest.mark.asyncio
async def test_customer_factory_does_not_create_missing_identity(buyer):
    """Dry-run and live Action authentication never enroll a new customer."""
    db, principal = buyer
    bot = await resolve_bot_context(
        db,
        authenticated_bot_id=principal.bot_id,
        authenticated_platform=Platform.TELEGRAM,
    )
    with pytest.raises(ActionRejected, match="action_customer_unavailable"):
        await customer_principal(db, verified_bot=bot, platform_user_id=9999)


@pytest.mark.asyncio
async def test_inactive_store_is_denied(buyer):
    """An active Bot does not override its Store's archived state."""
    db, principal = buyer
    store = await db.get(ShopStore, principal.store_id)
    store.state = "archived"
    await db.commit()
    with pytest.raises(ActionRejected, match="action_bot_unavailable"):
        await refresh_principal(db, principal)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["disabled", "paused", "maintenance"])
@pytest.mark.parametrize(
    "key", ["support.create_request", "order.list_customer_orders"]
)
async def test_registry_operational_gate_applies_to_every_action_category(
    buyer, state, key
):
    """The Registry disable switch also blocks non-catalog reads and writes."""
    from uuid import uuid4
    from sqlalchemy import func, select
    from models.shop_action import ShopActionExecution
    from models.shop_bot_operations import ShopBotOperations
    from models.shop_customer_support import ShopSupportTicket
    from services.shop_actions.contracts import Invocation
    from services.shop_actions.execution import invoke

    db, principal = buyer
    db.add(ShopBotOperations(bot_id=principal.bot_id, desired_state=state))
    await db.commit()
    result = await invoke(
        db,
        principal,
        Invocation(
            invocation_id=str(uuid4()),
            action_key=key,
            input={"body": "private note"} if key.startswith("support.") else {},
            idempotency_key=str(uuid4()),
        ),
    )
    assert (
        result.status == "unavailable" and result.error.code == "action_bot_unavailable"
    )
    assert await db.scalar(select(func.count()).select_from(ShopSupportTicket)) == 0
    assert await db.scalar(select(func.count()).select_from(ShopActionExecution)) == 0
