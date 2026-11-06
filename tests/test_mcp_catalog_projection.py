"""A versioned catalog projection supplies scalar Workflow text from real ACL data."""

import pytest

from models.shop_bot_catalog_acl import ShopBotProductRule
from services.shop_actions.catalog import actions
from services.shop_actions.execution import invoke
from services.shop_actions.simulation import simulate_action
from tests.test_action_adapters import request
from tests.test_action_security import buyer as buyer  # noqa: PLC0414
from tests.test_action_security import db as db  # noqa: PLC0414
from tests.test_shared_cart import seed


@pytest.mark.asyncio
async def test_search_v2_renders_only_visible_real_products(buyer):
    """New text is derived from the same page; a denied product stays absent."""
    session, principal = buyer
    first, second = seed(session)
    session.add(
        ShopBotProductRule(
            bot_id=principal.bot_id, product_id=second.id, effect="deny"
        )
    )
    await session.commit()
    result = await invoke(
        session,
        principal,
        request(
            "catalog.search_products",
            {"query": "محصول"},
            action_version="2.0.0",
        ),
    )
    assert result.status == "succeeded", result.model_dump()
    assert [row["id"] for row in result.output["items"]] == [first.id]
    assert first.name in result.output["display_text"]
    assert second.name not in result.output["display_text"]
    assert "1000" in result.output["display_text"].replace(",", "")


@pytest.mark.asyncio
async def test_search_v2_empty_text_is_honest_and_v1_stays_unchanged(buyer):
    """No synthetic product is displayed when the actual catalog has no match."""
    session, principal = buyer
    seed(session)
    await session.commit()
    for version in ("1.0.0", "2.0.0"):
        result = await invoke(
            session,
            principal,
            request(
                "catalog.search_products",
                {"query": "ABSENT-UNIQUE-CATALOG"},
                action_version=version,
            ),
        )
        assert result.status == "succeeded", result.model_dump()
        assert result.output["items"] == [] and result.output["total"] == 0
        if version == "1.0.0":
            assert set(result.output) == {"items", "total", "page", "has_more"}
        else:
            assert result.output["display_text"] == "محصولی پیدا نشد."


@pytest.mark.parametrize("platform", ["telegram", "bale"])
def test_search_v2_simulation_is_typed_and_unmistakably_synthetic(platform):
    """The pure simulator advertises the new scalar without opening a DB."""
    descriptor = actions().resolve("catalog.search_products", "2.0.0")
    assert descriptor.descriptor.side_effect == "read_only"
    result = simulate_action(
        "catalog.search_products",
        "2.0.0",
        {"query": "sample"},
        platform=platform,
    )
    assert "آزمایشی" in result["display_text"]
    assert len(result["display_text"]) <= 4000
