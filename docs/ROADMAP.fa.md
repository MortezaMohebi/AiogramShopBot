# نقشه راه اجرایی Fork

معنی وضعیت‌ها: `DONE` = کد Merge/تست‌شده؛ `IN PROGRESS` = پیاده‌سازی ناقص؛ `PLANNED` = نیازمند توسعه و تست. وجود یک مدل یا رابط در شاخه توسعه به معنی آمادگی Production نیست.

| فاز | خروجی قابل آزمون | وضعیت در شروع Fork |
|---|---|---|
| F0 | اهداف، معماری و معیارهای پذیرش مکتوب | DONE (documentation) |
| F1 | داشبورد SQLAdmin فارسی و RTL، منو و عنوان فیلدهای فارسی | IN PROGRESS (templates and labels committed; runtime visual review outstanding) |
| F2 | محصول مستقل و داینامیک، فایل و رضایت مستقل، CRUD مدیریتی | IN PROGRESS (models, admin and Alembic migration committed; upload/render not wired) |
| F3 | Media upload امن، Preview و ارسال فایل با Cache تفکیکی هر Bot | PLANNED |
| F4 | Menu Builder داینامیک از دیتابیس و نمایش به‌روز بدون Restart | IN PROGRESS (menu records/admin available; bot handlers still static) |
| F5 | Telegram adapter و اتصال واقعی کاتالوگ/رسانه/منو | PLANNED |
| F6 | Bale adapter، تست میدانی و سازگاری انواع پیام و دکمه | PLANNED |
| F7 | سفارش‌های مشترک و Inventory transaction-safe، مبالغ Decimal | PLANNED |
| F8 | Payment method، تأیید امضای Callback، Idempotency و Refund | PLANNED |
| F9 | RBAC، Multi-admin، Audit، Backup، مانیتورینگ و تست بار | PLANNED |

## تحویل هر فاز

- Migration قابل Rollback یا دستور بازیابی پایگاه داده.
- Test Caseهای قابل تکرار + شاهد نتیجه اجرا.
- هیچ تغییر در `master` تا زمان Code Review و پذیرش.
- در صورت نیاز به داده واقعی، Fixture دستی به‌جای Hard-coded کردن محصول نمونه.
- حفظ جریان خرید موجود تا هنگام جایگزینی ایمن و پوشش تست.

## ترتیب اولویت

F1 و F2 پایه داشبورد هستند. F3/F4 راه ارائه کاتالوگ پویا را باز می‌کنند. سپس F5 و F6 باید روی یک Core مشترک قابل تست اجرا شوند. F7 و F8 تنها بعد از تعیین نوع محصول و روش واقعی پرداخت تکمیل می‌شوند. F9 از ابتدا به‌صورت افزایشی اعمال می‌شود.

## مواردی که نباید ناآگاهانه حذف شوند

- داده‌های `Item`، `Buy`، `BuyItem` و `Review` قبلی، تا تهیه Migration و تأیید انتقال داده.
- قابلیت‌های legacy پرداخت رمزارز یا Multibot بدون Feature Flag / داده‌برداری؛ از UI جدید پنهان شوند اما حذف ناگهانی انجام نشود.
- تاریخچه سفارش و تراکنش‌های پرداخت.
