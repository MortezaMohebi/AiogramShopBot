"""Legacy audit rows cannot make live typed Actions available."""
from types import SimpleNamespace

from services.shop_action_catalog import contextual_view
from services.shop_actions.definitions import definition


def test_historical_bot_row_is_never_live_action_authority():
    descriptor = definition("catalog.search_products", "1.0.0").descriptor
    bot = SimpleNamespace(runtime_owner="legacy", status="legacy", platform="telegram", credential_version=None)
    env = ("store", SimpleNamespace(state="active"), bot, None, None)
    result = contextual_view(descriptor, env, SimpleNamespace(role="superadmin"))
    assert not result["availability"]["available"]
    assert "action_bot_unavailable" in result["availability"]["reasons"]
