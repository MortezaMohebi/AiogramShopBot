"""Beta P1 contract for one Telegram/Bale customer menu and safe search."""

from __future__ import annotations

from channels.contracts import Platform
from services.shop_customer_menu import DEFAULT_MENU, menu_rows, normalize_menu


def test_six_main_menu_buttons_have_identical_callbacks_on_both_channels():
    """The platform adapter may differ, but the business navigation may not."""
    expected = (
        "shop:categories", "ux:search", "shop:cart",
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
