"""Persian transactional email content with safe HTML and plain-text parts."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class TransactionalEmail:
    """A prepared subject and two accessible alternatives."""

    subject: str
    plain: str
    html: str


_COPY = {
    "invite": (
        "دعوت به مدیریت فروشگاه",
        "برای ساخت حساب مدیریت خود از پیوند زیر استفاده کنید. "
        "این پیوند فقط یک‌بار معتبر است.",
    ),
    "reset": (
        "بازیابی رمز عبور مدیریت",
        "درخواست بازیابی رمز عبور ثبت شده است. "
        "اگر این درخواست را شما داده‌اید، از پیوند زیر استفاده کنید.",
    ),
    "mfa_notice": (
        "هشدار تغییر احراز هویت دومرحله‌ای",
        "وضعیت احراز هویت دومرحله‌ای حساب شما تغییر کرده است. "
        "اگر این کار را شما انجام نداده‌اید، با مدیر سامانه تماس بگیرید.",
    ),
    "smtp_test": (
        "آزمون ارسال ایمیل فروشگاه",
        "تنظیم ارسال ایمیل با موفقیت آزمایش شد.",
    ),
}


def render_email(kind: str, *, recipient: str, link: str = "") -> TransactionalEmail:
    """Render one allowlisted message without interpolating raw HTML."""
    if kind not in _COPY:
        raise ValueError("Unknown transactional email template.")
    if not recipient or any(char in recipient for char in "\r\n"):
        raise ValueError("Invalid email recipient label.")
    if kind in {"invite", "reset"}:
        target = urlsplit(link)
        if (
            target.scheme != "https" or not target.netloc
            or target.username or target.password
            or any(char in link for char in "\r\n")
        ):
            raise ValueError("A public HTTPS action link is required.")
    elif link:
        raise ValueError("This template does not contain an action link.")
    subject, body = _COPY[kind]
    plain = f"{recipient} عزیز،\n\n{body}"
    if link:
        plain += (
            f"\n\n{link}\n\n"
            "اگر درخواست از طرف شما نبوده، این ایمیل را نادیده بگیرید."
        )
    safe_link = escape(link, quote=True)
    action = (
        f'<p><a href="{safe_link}" style="display:inline-block;'
        'padding:12px 20px;background:#f59a23;color:#151515;'
        'text-decoration:none;border-radius:8px">باز کردن پیوند امن</a></p>'
        if link else ""
    )
    html = (
        '<div dir="rtl" lang="fa" style="font-family:Tahoma,Arial,sans-serif;'
        'max-width:560px;margin:auto;color:#202124;line-height:1.9">'
        f'<h1 style="font-size:20px">{escape(subject)}</h1>'
        f'<p>{escape(recipient)} عزیز،</p><p>{escape(body)}</p>{action}'
        '<p style="font-size:13px;color:#666">'
        'این پیام از سامانهٔ مدیریت فروشگاه ارسال شده است.</p></div>'
    )
    return TransactionalEmail(subject, plain, html)
