"""P4 support and fulfillment permission/transition regressions for the Beta."""

from __future__ import annotations

import pytest

from services.shop_fulfillment import validate_fulfillment_transition
from services.shop_customer_support import validate_ticket_body


@pytest.mark.parametrize("current,next_status", [
    ("processing", "ready"),
    ("ready", "shipped"),
    ("shipped", "delivered"),
])
def test_physical_fulfillment_happy_path(current, next_status):
    """Physical fulfillment is allowed only through genuine forward steps."""
    assert validate_fulfillment_transition(
        current, next_status, physical=True, paid=True,
    )


@pytest.mark.parametrize("current,next_status", [
    ("processing", "delivered"),
    ("shipped", "processing"),
    ("delivered", "ready"),
])
def test_fulfillment_rejects_out_of_order_state(current, next_status):
    """A manager cannot mark an unshipped parcel as delivered."""
    with pytest.raises(ValueError):
        validate_fulfillment_transition(
            current, next_status, physical=True, paid=True,
        )


def test_digital_delivery_requires_settled_paid_receipt():
    """No digital entitlement may be released on pre-checkout alone."""
    with pytest.raises(ValueError):
        validate_fulfillment_transition(
            "processing", "delivered", physical=False, paid=False,
        )
    # A paid receipt alone proves money, not a secure digital asset delivery.
    # Until the media/license pipeline emits proof, "delivered" must be denied.
    with pytest.raises(ValueError):
        validate_fulfillment_transition(
            "processing", "delivered", physical=False, paid=True,
        )


def test_ticket_body_rejects_control_characters_and_empty():
    """Bot-sent ticket text must be bounded and suitable for plain text."""
    assert validate_ticket_body("ارسال سفارش من تأخیر دارد.") == "ارسال سفارش من تأخیر دارد."
    for text in ("", " ", "\x00", "A" * 4001):
        with pytest.raises(ValueError):
            validate_ticket_body(text)
