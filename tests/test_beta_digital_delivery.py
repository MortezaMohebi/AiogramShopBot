"""Pure offline safety gates for digital file and license delivery."""

import pytest

from services.shop_digital_rules import (
    DeliveryPolicyError, allow_digital_delivery,
    safe_digital_filename, validate_delivery_transition,
    validate_license_code,
)


def test_file_key_cannot_reference_catalog_media_or_parent_path():
    """Customer delivery must use randomly generated private storage keys."""
    assert safe_digital_filename("a" * 32 + ".pdf").endswith(".pdf")
    for key in ("../secret.txt", "/etc/passwd", "public.jpg", "abc.pdf"):
        with pytest.raises(DeliveryPolicyError):
            safe_digital_filename(key)


def test_payment_and_owner_are_required_before_sending():
    """Neither precheckout nor a random Bot identity unlocks the asset."""
    assert allow_digital_delivery(
        paid=True, correct_store=True, correct_bot=True,
        asset_ready=True, refunded=False,
    )
    for override in ({"paid": False}, {"correct_store": False},
                     {"correct_bot": False}, {"asset_ready": False},
                     {"refunded": True}):
        flags = dict(
            paid=True, correct_store=True, correct_bot=True,
            asset_ready=True, refunded=False,
        )
        flags.update(override)
        with pytest.raises(DeliveryPolicyError):
            allow_digital_delivery(**flags)


def test_unknown_send_result_may_not_retry():
    """Network timeouts quarantine a claimed delivery, never auto-replay."""
    assert validate_delivery_transition("queued", "sending")
    assert validate_delivery_transition("sending", "needs_review")
    with pytest.raises(DeliveryPolicyError):
        validate_delivery_transition("needs_review", "queued")
    with pytest.raises(DeliveryPolicyError):
        validate_delivery_transition("delivered", "sending")


def test_license_text_is_printable_and_bounded():
    """No unbounded secret is accepted or logged."""
    assert validate_license_code("  LIC-1234  ") == "LIC-1234"
    for key in ("a", "\nCODE", "X" * 129):
        with pytest.raises(DeliveryPolicyError):
            validate_license_code(key)
