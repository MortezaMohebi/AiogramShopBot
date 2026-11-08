"""Beta P1 contract for one Telegram/Bale customer menu and safe search."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from channels.contracts import Platform
from models.shop_checkout import ShopCart
from models.shop_customer_navigation import ShopBotMenuPolicy, ShopCustomerChatState
from services.shop_customer_menu import DEFAULT_MENU, MENU_LABELS, menu_rows, normalize_menu
from services.shop_multibot_dispatch import dispatch
from tests.test_beta_cart_form_navigation import setup_dispatch
from tests.test_beta_paused_customer_support import raw
from tests.test_shared_cart import db


def test_six_main_menu_buttons_have_identical_callbacks_on_both_channels():
    """The platform adapter may differ, but the business navigation may not."""
    expected = (
        "shop:list:0", "ux:search", "shop:cart",
        "shop:orders", "ux:account", "ux:support",
    )
    telegram = menu_rows(DEFAULT_MENU, platform=Platform.TELEGRAM, cart_enabled=True)
    bale = menu_rows(DEFAULT_MENU, platform=Platform.BALE, cart_enabled=True)
    assert [row[0].callback_data for row in telegram] == list(expected)
    assert [row[0].callback_data for row in bale] == list(expected)


def test_disabled_cart_does_not_show_payment_entry():
    """Menu must reflect per-bot cart permission rather than global provider."""
    visible = menu_rows(DEFAULT_MENU, platform=Platform.BALE, cart_enabled=False)
    assert all(
        button.callback_data != "shop:cart"
        for row in visible for button in row
    )


def test_custom_menu_rejects_duplicate_or_unknown_routes():
    """An administrator cannot inject provider API methods or callback URLs."""
    for values in (
        ["shop", "shop"],
        ["shop", "refundStarPayment"],
        ["shop", "https://example.com"],
        [],
    ):
        try:
            normalize_menu(values)
        except ValueError:
            continue
        raise AssertionError(f"Invalid menu was accepted: {values}")


def test_customer_search_callback_remains_within_platform_byte_budget():
    """All menu callbacks must fit the Telegram/Bale 64-byte allowance."""
    for row in menu_rows(DEFAULT_MENU, platform=Platform.TELEGRAM, cart_enabled=True):
        for button in row:
            assert len(button.callback_data.encode("utf-8")) <= 64


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_home_and_keyboard_follow_ordered_live_policy(db, monkeypatch, platform):
    """Policy changes revoke both old inline and native menu shortcuts."""
    scope, client = await setup_dispatch(db, monkeypatch, platform)
    assert (await dispatch(scope, client, raw(message="/start")))["status"] == "processed"
    state = db.session.get(ShopCustomerChatState, (scope.bot_id, 101))
    view = state.view_state["active"]
    assert view["actions"] == [row[0].callback_data for row in menu_rows(
        DEFAULT_MENU, platform=platform, cart_enabled=True,
    )]
    slot = view["actions"].index("shop:cart")
    old = raw(callback=f"v1:{view['generation']}:{slot}")
    old["callback_query"]["message"]["message_id"] = state.ui_message_id
    db.session.add(ShopBotMenuPolicy(
        bot_id=scope.bot_id, store_id=scope.store_id,
        actions_json='["orders","shop","support"]',
    ))
    db.session.commit()
    await dispatch(scope, client, old)
    await dispatch(scope, client, raw(message=MENU_LABELS["cart"]))
    assert state.view_state["active"]["actions"] == ["shop:orders", "shop:list:0", "ux:support"]
    assert db.session.scalars(select(ShopCart)).all() == []
    expected = [MENU_LABELS[key] for key in ("orders", "shop", "support")]
    if platform == Platform.TELEGRAM:
        keyboards = [item["reply_markup"].keyboard for item in client.messages
                     if hasattr(item.get("reply_markup"), "keyboard")]
        assert [button.text for row in keyboards[-1] for button in row] == expected
    else:
        keyboards = [item["keyboard_rows"] for item in client.messages
                     if item.get("keyboard_rows") is not None]
        assert [button for row in keyboards[-1] for button in row] == expected
    assert len(keyboards) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_legacy_native_shortcut_refreshes_keyboard_on_first_use(db, monkeypatch, platform):
    """Existing shoppers get current shortcuts even without a stored keyboard fingerprint."""
    scope, client = await setup_dispatch(db, monkeypatch, platform)
    db.session.add(ShopBotMenuPolicy(
        bot_id=scope.bot_id, store_id=scope.store_id, actions_json='["shop","orders"]',
    ))
    db.session.commit()
    payload = raw(message=MENU_LABELS["orders"])
    for _ in range(2):
        assert (await dispatch(scope, client, payload))["status"] == "processed"
    state = db.session.get(ShopCustomerChatState, (scope.bot_id, 101))
    assert state.view_state.get("keyboard")
    if platform == Platform.TELEGRAM:
        keyboards = [item["reply_markup"].keyboard for item in client.messages
                     if hasattr(item.get("reply_markup"), "keyboard")]
        labels = [button.text for row in keyboards[0] for button in row]
    else:
        keyboards = [item["keyboard_rows"] for item in client.messages
                     if item.get("keyboard_rows") is not None]
        labels = [button for row in keyboards[0] for button in row]
    assert labels == [MENU_LABELS["shop"], MENU_LABELS["orders"]]
    assert len(keyboards) == 1
