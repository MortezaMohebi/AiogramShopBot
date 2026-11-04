"""Pure, bounded checkout approval copy for the customer chat.

No provider side effects occur when composing the message. Pricing must
already have been verified and expressed in the correct provider currency.
"""

from __future__ import annotations


def checkout_confirmation_text(
    *, item_count: int, price_label: str, checkout_mode: str,
    terms_version: str, split: bool,
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
        "ثبت و آماده‌سازی پرداخت"
        if checkout_mode == "instant"
        else "ثبت درخواست بررسی فروشنده"
    )
    split_note = (
        "با تأیید، دو سفارش جدا ساخته می‌شود و پرداخت هرکدام مستقل است.\n"
        if split else ""
    )
    return (
        "🧾 بررسی نهایی سفارش\n"
        f"تعداد اقلام: {item_count}\n"
        f"مبلغ نهایی: {price_label}\n"
        f"مسیر: {mode_label}\n"
        f"شرایط خرید: نسخهٔ {terms_version}\n"
        f"{split_note}"
        "با تأیید، شرایط خرید این نسخه را می‌پذیرید. "
        "متن کامل از /terms قابل مشاهده است؛ هنوز وجهی دریافت نشده."
    )
