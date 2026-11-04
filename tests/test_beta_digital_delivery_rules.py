"""The digital fulfillment pipeline must never deliver before paid receipt."""

from pathlib import Path

import pytest

from services.shop_digital_rules import (
    DeliveryPolicyError,
    allow_digital_delivery,
    validate_delivery_transition,
    safe_digital_filename,
)


def test_paid_receipt_and_exact_origin_required():
    """A precheckout ACK, wrong Bot or missing asset is not a delivery grant."""
    assert allow_digital_delivery(
        paid=True, correct_store=True, correct_bot=True,
        asset_ready=True, refunded=False,
    )
    for kwargs in (
        {"paid": False},
        {"correct_store": False},
        {"correct_bot": False},
        {"asset_ready": False},
        {"refunded": True},
    ):
        conditions = {
            "paid": True, "correct_store": True,
            "correct_bot": True, "asset_ready": True, "refunded": False,
        }
        conditions.update(kwargs)
        with pytest.raises(DeliveryPolicyError):
            allow_digital_delivery(**conditions)


def test_unknown_outcome_never_requeues_itself():
    """A transport timeout is quarantine, not permission for a retry."""
    assert validate_delivery_transition("queued", "sending")
    assert validate_delivery_transition("sending", "delivered")
    assert validate_delivery_transition("sending", "needs_review")
    for a, b in (
        ("needs_review", "queued"),
        ("delivered", "sending"),
        ("sending", "queued"),
    ):
        with pytest.raises(DeliveryPolicyError):
            validate_delivery_transition(a, b)


def test_no_public_path_or_user_supplied_file_names():
    """Only server-generated IDs may identify files inside digital vault."""
    assert safe_digital_filename("a" * 32 + ".pdf") == "a" * 32 + ".pdf"
    for value in ("../secret.txt", "name.pdf", "/tmp/x.txt", "..\\evil", "x" * 50):
        with pytest.raises(DeliveryPolicyError):
            safe_digital_filename(value)
