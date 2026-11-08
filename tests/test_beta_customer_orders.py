"""Customer order authorization does not rely on raw numeric messenger IDs."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from channels.contracts import Platform
from models.shop_content import ShopOrder
from services.shop_customer_orders import order_owner_clause
from services.shop_orders import ShopOrdersFlow
from tests.schema_support import test_bot_context
from tests.test_shared_cart import db, event, seed


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_twenty_order_actions_fit_into_versioned_views(db, platform):
    """Every existing order remains reachable within the active slot budget."""
    product, _ = seed(db)
    context = test_bot_context(platform)
    db.session.add_all([
        ShopOrder(
            store_id=context.store_id, bot_id=context.bot_id,
            platform=platform.value, platform_user_id=101, chat_id=101,
            product_id=product.id, product_name_snapshot=product.name,
            unit_price_irr=1000, total_irr=1000, status="paid",
            provider="manual_review", invoice_payload=f"test-order-{i}",
        )
        for i in range(20)
    ])
    db.session.commit()
    flow = ShopOrdersFlow(bot_context=context)
    action = "shop:orders"
    order_controls = []
    for _ in range(4):
        reply = await flow.reply(event(platform, callback=action), db)
        controls = [button.callback_data for row in reply.rows for button in row]
        assert len(controls) <= 32
        order_controls.extend(a for a in controls if a.startswith("shop:refundorder:"))
        if len(order_controls) == 20:
            break
        action = next(
            button.callback_data for row in reply.rows for button in row
            if button.label == "صفحه بعد"
        )
    assert len(set(order_controls)) == 20


def test_verified_bot_identity_tuples_scope_historical_orders():
    """Previous Bot orders remain readable after verified Customer link."""
    clause = order_owner_clause(
        store_id="store-a", identity_keys=[
            ("bot-telegram", "telegram", 101),
            ("bot-bale", "bale", 202),
        ],
    )
    query = select(1).where(clause).compile(
        dialect=postgresql.dialect(),
    )
    sql = str(query).lower()
    assert "shop_orders.store_id" in sql
    assert "shop_orders.bot_id" in sql
    assert "shop_orders.platform_user_id" in sql
    assert "shop_orders.platform" in sql


def test_unlinked_customer_cannot_get_all_orders_with_same_user_number():
    """A bare platform_user_id never authorizes another Bot's order."""
    clause = order_owner_clause(
        store_id="store-a", identity_keys=[
            ("bot-alpha", "telegram", 55),
        ],
    )
    statement = select(1).where(clause).compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    )
    sql = str(statement)
    assert "bot-alpha" in sql
    assert "bot-beta" not in sql


def test_empty_verified_identity_set_is_denied():
    """An empty or untrusted cluster cannot see historical purchases."""
    sql = str(order_owner_clause(
        store_id="store-a", identity_keys=[],
    ).compile(dialect=postgresql.dialect())).lower()
    assert "false" in sql


def test_identity_cluster_limits_resource_usage():
    """Large malformed ownership sets never create unbounded SQL clauses."""
    with pytest.raises(ValueError):
        order_owner_clause(
            store_id="store-a",
            identity_keys=[("bot-x", "telegram", n) for n in range(150)],
        )
