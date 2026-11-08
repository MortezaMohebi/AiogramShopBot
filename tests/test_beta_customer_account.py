"""Beta P2 customer account ownership and provider contact verification."""

from __future__ import annotations

import pytest

from channels.contracts import InboundEvent, Platform, normalize_update
from models.shop_multibot import ShopBot
from services.shop_customer_account import CustomerAccountFlow, verified_contact
from tests.test_beta_cart_form_navigation import setup_dispatch
from tests.test_shared_cart import db, event


@pytest.mark.parametrize("platform", [Platform.TELEGRAM, Platform.BALE])
def test_verified_contact_requires_exact_bot_message_sender(platform):
    """A shared phone number cannot prove ownership of another chat user."""
    source = {
        "message": {
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "first_name": "Customer"},
            "contact": {"user_id": 42, "phone_number": "+989123456789"},
        }
    }
    event = normalize_update(platform, source)
    assert event is not None
    assert verified_contact(event) == "+989123456789"
    spoof = {**source, "message": {
        **source["message"],
        "contact": {"user_id": 99, "phone_number": "+989123456789"},
    }}
    wrong = normalize_update(platform, spoof)
    assert wrong is not None
    with pytest.raises(ValueError):
        verified_contact(wrong)


def test_callback_ids_fit_bot_api():
    """Wishlist and address callbacks remain beneath 64 UTF-8 bytes."""
    for callback in ("ux:wish:toggle:9223372036854775807", "ux:address:choose:9223372036854775807"):
        assert 0 < len(callback.encode("utf-8")) <= 64


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_account_groups_keep_existing_actions_within_two_taps(db, monkeypatch, platform):
    """Four Account choices preserve every previously offered destination."""
    scope, _ = await setup_dispatch(db, monkeypatch, platform)
    flow = CustomerAccountFlow(bot_context=scope)

    async def open_action(action):
        return await flow.reply(event(platform, callback=action), db)

    def controls(reply):
        return [button.callback_data for row in reply.rows for button in row]

    account = await open_action("ux:account")
    assert [action for action in controls(account) if action != "shop:home"] == [
        "ux:profile", "ux:addresses", "ux:account:benefits", "ux:account:settings",
    ]
    for group, expected in (
        ("ux:account:benefits", ("ux:wallet", "ux:wishlist", "ux:referral", "ux:stock:list")),
        ("ux:account:settings", ("ux:links", "ux:notifications", "ux:language", "ux:privacy")),
    ):
        assert controls(await open_action(group)) == [*expected, "ux:account"]
        for action in expected:
            assert group in controls(await open_action(action))


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_verification_and_linked_accounts_use_customer_language(db, monkeypatch, platform):
    """Explain the native proof and display a recognizable name, never a bot ID."""
    scope, _ = await setup_dispatch(db, monkeypatch, platform)
    bot = db.session.get(ShopBot, scope.bot_id)
    bot.name = "فروشگاه نمونه"
    db.session.commit()
    flow = CustomerAccountFlow(bot_context=scope)
    profile = await flow.reply(event(platform, callback="ux:profile"), db)
    prompt = await flow.reply(event(platform, callback="ux:phone"), db)
    linked = await flow.reply(event(platform, callback="ux:links"), db)
    assert "Contact" not in profile.text and "Client" not in prompt.text
    assert "اشتراک شمارهٔ تماس" in prompt.text and "برای تماس" in prompt.text
    assert "فروشگاه نمونه" in linked.text and scope.bot_id[:8] not in linked.text
    assert ("تلگرام" if platform == Platform.TELEGRAM else "بله") in linked.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_invalid_address_action_keeps_named_recovery(db, monkeypatch, platform):
    """A missing form still supplies a text action to the address book."""
    scope, _ = await setup_dispatch(db, monkeypatch, platform)
    reply = await CustomerAccountFlow(bot_context=scope).reply(
        event(platform, callback="ux:address:confirm"), db,
    )
    controls = [button for row in reply.rows for button in row]
    assert any(button.callback_data == "ux:addresses" for button in controls)
    assert all(any(char.isalpha() for char in button.label) for button in controls)
