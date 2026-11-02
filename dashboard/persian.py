"""Persian model metadata for the existing SQLAdmin dashboard.

The labels are only interface metadata and never represent product records.
"""

from __future__ import annotations

from typing import Any


VIEW_LABELS = {
    "UserAdmin": [
        "مشتری",
        "مشتریان",
        "مشتریان"
    ],
    "BuyAdmin": [
        "سفارش",
        "سفارش‌ها",
        "فروش"
    ],
    "ShippingOptionAdmin": [
        "روش ارسال",
        "روش‌های ارسال",
        "فروش"
    ],
    "CouponAdmin": [
        "کد تخفیف",
        "کدهای تخفیف",
        "بازاریابی"
    ],
    "CategoryAdmin": [
        "دسته‌بندی",
        "دسته‌بندی‌ها",
        "کاتالوگ"
    ],
    "SubcategoryAdmin": [
        "زیردسته",
        "زیردسته‌ها",
        "کاتالوگ"
    ],
    "ItemAdmin": [
        "واحد موجودی",
        "واحدهای موجودی",
        "کاتالوگ"
    ],
    "DepositAdmin": [
        "افزایش اعتبار",
        "افزایش اعتبارها",
        "مالی"
    ],
    "BuyItemAdmin": [
        "قلم سفارش",
        "اقلام سفارش",
        "فروش"
    ],
    "PaymentAdmin": [
        "پرداخت",
        "پرداخت‌ها",
        "مالی"
    ],
    "CartAdmin": [
        "سبد خرید",
        "سبدهای خرید",
        "فروش"
    ],
    "CartItemAdmin": [
        "قلم سبد",
        "اقلام سبد",
        "فروش"
    ],
    "ReferralBonusAdmin": [
        "پاداش معرفی",
        "پاداش‌های معرفی",
        "بازاریابی"
    ],
    "ReviewAdmin": [
        "نظر مشتری",
        "نظرهای مشتریان",
        "محتوا"
    ]
}

FIELD_LABELS = {
    "id": "شناسه",
    "name": "نام",
    "description": "توضیحات",
    "price": "قیمت",
    "total_price": "مبلغ کل",
    "discount": "تخفیف",
    "category": "دسته‌بندی",
    "subcategory": "زیردسته",
    "item_type": "نوع کالا",
    "is_sold": "فروخته شده",
    "is_new": "جدید",
    "is_active": "فعال",
    "is_disabled": "غیرفعال",
    "status": "وضعیت",
    "quantity": "تعداد",
    "rating": "امتیاز",
    "text": "متن",
    "image_id": "شناسه تصویر",
    "media_id": "شناسه رسانه",
    "telegram_username": "نام کاربری تلگرام",
    "telegram_id": "شناسه تلگرام",
    "buy_datetime": "زمان سفارش",
    "registered_at": "زمان عضویت",
    "create_datetime": "زمان ثبت",
    "shipping_address": "نشانی ارسال",
    "track_number": "کد رهگیری",
    "is_paid": "پرداخت شده",
    "is_banned": "مسدود شده",
    "language": "زبان",
    "top_up_amount": "اعتبار شارژشده",
    "consume_records": "اعتبار مصرف‌شده",
    "private_data": "اطلاعات تحویل دیجیتال",
    "user_id": "کاربر",
    "buyer_id": "خریدار",
    "category_id": "دسته‌بندی",
    "subcategory_id": "زیردسته",
    "shipping_option_id": "روش ارسال",
    "coupon_id": "کد تخفیف",
    "item_ids": "شناسه اقلام",
    "can_receive_messages": "دریافت پیام",
    "referral_code": "کد معرفی"
}


def localize_model_view(view: type[Any]) -> type[Any]:
    """Apply Persian titles and field labels before registering the SQLAdmin view."""
    metadata = VIEW_LABELS.get(view.__name__)
    if metadata:
        view.name, view.name_plural, view.category = metadata

    model = getattr(view, "model", None)
    if model is None:
        return view

    labels = dict(getattr(view, "column_labels", {}) or {})
    for field, translation in FIELD_LABELS.items():
        if hasattr(model, field):
            labels.setdefault(field, translation)
    view.column_labels = labels
    return view
