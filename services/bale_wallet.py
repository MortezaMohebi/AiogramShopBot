"""Shared customer-safe checkout refusal for commerce flows."""


class CheckoutRejected(ValueError):
    """Refuse checkout without exposing internal payment details."""
