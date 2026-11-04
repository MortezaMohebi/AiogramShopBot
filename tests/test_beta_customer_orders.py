"""Customer order authorization does not rely on raw numeric messenger IDs."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from services.shop_customer_orders import order_owner_clause


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
