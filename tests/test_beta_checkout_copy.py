"""Independent customer confirmation copy validation for split checkout."""

from services.shop_checkout_copy import checkout_confirmation_text


def test_split_checkout_includes_both_independent_invoice_currencies():
    """Mixed carts must not show one misleading aggregate Rial price."""
    message = checkout_confirmation_text(
        item_count=3,
        price_label="200٬000 ریال + 19 Stars (XTR)",
        checkout_mode="manual",
        terms_version="v2",
        split=True,
    )
    assert "200٬000 ریال + 19 Stars (XTR)" in message.replace("\u2066", "").replace("\u2069", "")
    assert "دو سفارش" in message
    assert "پرداخت هرکدام مستقل" in message
    assert "v2" in message


def test_single_invoice_has_no_split_language():
    """One-order confirmation must not imply two payment obligations."""
    message = checkout_confirmation_text(
        item_count=1, price_label="32 Stars (XTR)",
        checkout_mode="instant", terms_version="v1", split=False,
    )
    assert "32 Stars (XTR)" in message
    assert "دو سفارش" not in message
    assert "آماده‌سازی پرداخت" in message


def test_mixed_direction_reference_keeps_currency_and_terms_visible():
    """Isolate Latin references inside Persian copy without altering either value."""
    message = checkout_confirmation_text(
        item_count=3, price_label="200٬000 ریال + 19 Stars (XTR)",
        checkout_mode="manual", terms_version="v2-2026", split=True,
    )
    assert "200٬000 ریال" in message
    assert "\u206619 Stars (XTR)\u2069" in message
    assert "\u2066v2-2026\u2069" in message
    assert "مشاهده شرایط خرید" in message
