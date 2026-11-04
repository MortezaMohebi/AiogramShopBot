"""Deterministic mixed Checkout Group identity, no numeric ID collision."""

from services.shop_mixed_checkout_orders import checkout_idempotency_key


def test_exact_checkout_identity_is_fixed_width_and_bot_scoped():
    """An unhashed Bot UUID + large numeric user IDs cannot exceed DB limits."""
    a = checkout_idempotency_key(
        bot_id="a" * 36, user_id=2**40, cart_id=456, revision=99999,
    )
    b = checkout_idempotency_key(
        bot_id="b" * 36, user_id=2**40, cart_id=456, revision=99999,
    )
    assert len(a) == 64 and a != b
    assert a == checkout_idempotency_key(
        bot_id="a" * 36, user_id=2**40, cart_id=456, revision=99999,
    )
