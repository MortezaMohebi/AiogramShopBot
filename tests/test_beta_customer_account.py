"""Beta P2 customer account ownership and provider contact verification."""

from __future__ import annotations

import pytest

from channels.contracts import InboundEvent, Platform, normalize_update
from services.shop_customer_account import verified_contact, validate_address


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


def test_address_validation_requires_structured_bounded_values():
    """Chat address entries are validated instead of storing arbitrary text."""
    valid = "خانه|گیرنده نمونه|09123456789|تهران|تهران|خیابان نمونه پلاک ۱|1234567890"
    data = validate_address(valid)
    assert data["label"] == "خانه"
    assert data["city"] == "تهران"
    with pytest.raises(ValueError):
        validate_address("نشانی غیر ساختاریافته")
    with pytest.raises(ValueError):
        validate_address("a|b|c|d|e|f|" + "9" * 1000)


def test_callback_ids_fit_bot_api():
    """Wishlist and address callbacks remain beneath 64 UTF-8 bytes."""
    for callback in ("ux:wish:toggle:9223372036854775807", "ux:address:choose:9223372036854775807"):
        assert 0 < len(callback.encode("utf-8")) <= 64
