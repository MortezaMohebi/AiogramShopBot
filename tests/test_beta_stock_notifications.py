"""P5 notification consent, stock alert and no-blind-retry regression."""

from __future__ import annotations

import pytest

from services.shop_customer_notifications import (
    notification_permitted,
    validate_outbox_transition,
)


def test_transactional_notice_not_misclassified_as_marketing():
    """Order payment notices can be sent only for their authenticated owner."""
    assert notification_permitted(
        topic="order", advertising_consent=False, explicit_request=False,
    )
    assert notification_permitted(
        topic="ticket", advertising_consent=False, explicit_request=False,
    )


def test_marketing_needs_bot_scoped_explicit_consent():
    """Do not inherit consent from a linked identity in another Bot."""
    assert not notification_permitted(
        topic="marketing", advertising_consent=False, explicit_request=False,
    )
    assert notification_permitted(
        topic="marketing", advertising_consent=True, explicit_request=False,
    )


def test_stock_alert_requires_explicit_subscription():
    """Inventory availability is a user-requested transactional notification."""
    assert not notification_permitted(
        topic="stock", advertising_consent=True, explicit_request=False,
    )
    assert notification_permitted(
        topic="stock", advertising_consent=False, explicit_request=True,
    )


def test_uncertain_outcome_never_requeues_or_resends():
    """Unknown provider response must be reviewed rather than automatically retried."""
    assert validate_outbox_transition("queued", "processing")
    assert validate_outbox_transition("processing", "sent")
    assert validate_outbox_transition("processing", "needs_review")
    with pytest.raises(ValueError):
        validate_outbox_transition("needs_review", "queued")
    with pytest.raises(ValueError):
        validate_outbox_transition("processing", "queued")
    with pytest.raises(ValueError):
        validate_outbox_transition("sent", "processing")
