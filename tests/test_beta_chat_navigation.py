"""Navigating away from forms clears only the current Bot's chat state."""

from services.shop_customer_experience import should_clear_chat_state


def test_customer_navigation_clears_pending_address_or_search_forms():
    """Going Home or to another core page must not consume the next free text."""
    for action in (
        "shop:home", "shop:categories", "shop:cart",
        "shop:orders", "ux:account", "ux:support", "shop:item:123",
    ):
        assert should_clear_chat_state(action, "")


def test_form_actions_and_unknown_callbacks_do_not_cancel_themselves():
    """Clicking an awaited form button does not discard the form prematurely."""
    for action in ("ux:search", "ux:ticket:topic:general", "ux:phone"):
        assert not should_clear_chat_state(action, "")
    assert not should_clear_chat_state("", "متن درخواست مشتری")


def test_start_or_menu_command_clear_pending_form():
    """A new session starts clean in either messaging provider."""
    assert should_clear_chat_state("", "/start")
    assert should_clear_chat_state("", "/menu")
