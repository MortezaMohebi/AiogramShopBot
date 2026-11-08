"""Pure, bounded checkout approval copy for the customer chat.

No provider side effects occur when composing the message. Pricing must
already have been verified and expressed in the correct provider currency.
"""

from __future__ import annotations

import re

_STAR_AMOUNT = re.compile(r"[0-9][0-9,٬]* Stars \(XTR\)")


def isolate_reference(value: str) -> str:
    """Keep an ASCII reference in reading order within Persian text."""
    return f"\u2066{value}\u2069" if value.isascii() else value


def checkout_confirmation_text(
    *, item_count: int, price_label: str, checkout_mode: str,
    terms_version: str, split: bool, delivery_label: str = "",
) -> str:
    """Explain terms and distinct payments without misleading currency totals."""
    if (
        type(item_count) is not int or not 1 <= item_count <= 100
        or not isinstance(price_label, str) or not 1 <= len(price_label) <= 160
        or checkout_mode not in {"manual", "instant"}
        or not isinstance(terms_version, str)
        or not 1 <= len(terms_version) <= 32
        or type(split) is not bool
    ):
        raise ValueError("Invalid finalized checkout summary inputs.")

    mode_label = (
        "ثبت سفارش و آماده‌سازی پرداخت در مرحلهٔ بعد"
        if checkout_mode == "instant"
        else "ثبت درخواست بررسی فروشنده"
    )
    split_note = (
        "با تأیید، دو سفارش جدا ساخته می‌شود و پرداخت هرکدام مستقل است.\n"
        if split else ""
    )
    delivery = f"{delivery_label}\n" if delivery_label else ""
    display_price = _STAR_AMOUNT.sub(lambda match: isolate_reference(match[0]), price_label)
    return (
        "🧾 بررسی نهایی سفارش\n"
        f"تعداد اقلام: {item_count}\n"
        f"مبلغ نهایی: {display_price}\n"
        f"{delivery}"
        f"مرحلهٔ بعد: {mode_label}\n"
        f"شرایط خرید: نسخهٔ {isolate_reference(terms_version)}\n"
        f"{split_note}"
        "متن کامل از «مشاهده شرایط خرید» در دسترس است. "
        "با ثبت سفارش، شرایط این نسخه را می‌پذیرید. هنوز وجهی دریافت نشده است."
    )
