"""Keep persisted human text legible without altering credentials or IDs."""

import pytest
from fastapi import HTTPException

from dashboard.next_api import validated_product_values
from services.shop_admin_security import SecurityRejected
from services.shop_bot_operations import public_https_url
from services.shop_customer_support import validate_ticket_body


def test_catalog_text_normalizes_controls_but_preserves_persian_spacing():
    """Catalog fields remain plain text with clean line breaks and half spaces."""
    result = validated_product_values({
        "name": " فیلتر\u200cهوا\u202e\x00 ",
        "description": " خط اول\r\nخط دوم\u2067 ",
        "sku": "Exact-0123",
        "price_irr": 1000,
    })
    assert result == {
        "name": "فیلتر\u200cهوا", "description": "خط اول\nخط دوم",
        "sku": "Exact-0123", "price": 1000,
    }


def test_catalog_name_must_remain_nonempty_after_cleanup():
    """A control-only required name is not a valid database value."""
    with pytest.raises(HTTPException) as result:
        validated_product_values({"name": "\x00\u202e\u200c"})
    assert result.value.status_code == 422


def test_support_normalizes_browser_line_endings():
    """Preserve Persian half spaces and readable multiline ticket bodies."""
    assert validate_ticket_body(" پیگیری\u200cسفارش\r\nلطفاً بررسی کنید ") == (
        "پیگیری\u200cسفارش\nلطفاً بررسی کنید"
    )


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "https://example.org/a\tb",
    "https://example.org/a\\b", "https://127.0.0.1/support",
    "https://127.1/support", "https://0177.0.0.1/support",
])
def test_support_link_rejects_unsafe_protocols_and_ambiguous_urls(url):
    """Support URLs use validation instead of plain text normalization."""
    with pytest.raises(SecurityRejected, match="invalid_support_url"):
        public_https_url(url)
