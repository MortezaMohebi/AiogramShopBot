"""Pure safety constraints for paid-only, single-attempt digital fulfillment.

Never equate a pre-checkout answer, received message, unconfirmed invoice or
previous provider timeout with a verified paid receipt or delivered asset.
"""

from __future__ import annotations

import re

_DIGITAL_KEY = re.compile(
    r"[0-9a-f]{32}\.(?:png|jpg|webp|gif|pdf|zip|mp4|mp3|ogg|txt)\Z"
)
_STATES = {
    "queued": frozenset({"sending", "blocked"}),
    "sending": frozenset({"delivered", "needs_review", "blocked"}),
    "delivered": frozenset(),
    "needs_review": frozenset(),
    "blocked": frozenset(),
}


class DeliveryPolicyError(ValueError):
    """A requested file/license delivery is not authorized or safe."""


def safe_digital_filename(key: str) -> str:
    """Allow only random server-created filenames, never arbitrary file paths."""
    if not isinstance(key, str) or not _DIGITAL_KEY.fullmatch(key):
        raise DeliveryPolicyError("Invalid private digital asset key.")
    return key


def allow_digital_delivery(
    *, paid: bool, correct_store: bool, correct_bot: bool,
    asset_ready: bool, refunded: bool,
) -> bool:
    """Require all five independent gates immediately before a provider send."""
    if not (
        paid is True and correct_store is True and correct_bot is True
        and asset_ready is True and refunded is False
    ):
        raise DeliveryPolicyError("Paid, owned, valid digital asset required.")
    return True


def validate_delivery_transition(current: str, next_status: str) -> bool:
    """Forbid automatic retry after any unknown or completed remote send."""
    if next_status not in _STATES.get(current, frozenset()):
        raise DeliveryPolicyError("Unsafe digital delivery status transition.")
    return True


def validate_license_code(value: str) -> str:
    """Accept one bounded printable license with no dangerous control chars."""
    if (
        not isinstance(value, str)
        or not 4 <= len(value.strip()) <= 128
        or any(not c.isprintable() for c in value)
    ):
        raise DeliveryPolicyError("Invalid digital license code.")
    return value.strip()
