# نقشه راه اجرایی Fork

معنی وضعیت‌ها: `DONE` = کد Merge/تست‌شده؛ `IN PROGRESS` = پیاده‌سازی ناقص؛ `PLANNED` = نیازمند توسعه و تست. وجود یک مدل یا رابط در شاخه توسعه به معنی آمادگی Production نیست.

| فاز | خروجی قابل آزمون | وضعیت در شروع Fork |
|---|---|---|
| F0 | اهداف، معماری و معیارهای پذیرش مکتوب | DONE (documentation) |
| F1 | داشبورد SQLAdmin فارسی و RTL، منو و عنوان فیلدهای فارسی | IN PROGRESS (templates and labels committed; runtime visual review outstanding) |
| F2 | محصول مستقل و داینامیک، فایل و رضایت مستقل، CRUD مدیریتی | IN PROGRESS (models, admin and Alembic migration committed; upload/render not wired) |
| F3 | Media upload امن، Preview و ارسال فایل با Cache تفکیکی هر Bot | PLANNED |
| F4 | منوی اصلی ثابت با متن فارسی؛ دکمه‌های کاتالوگ و جزئیات محصول از دیتابیس | PLANNED (بدون Menu Builder؛ صرفاً اتصال Catalog به Handlerهای موجود) |
| F5 | Telegram Adapter، اتصال کاتالوگ و حالت Direct/Proxy/Cloudflare Worker؛ Polling اختیاری | IN PROGRESS (پیاده‌سازی ثبت شد؛ تست Cloudflare و Aiogram واقعی باقی است) |
| F6 | Bale Adapter هم‌زمان با Telegram، Webhook و API | IN PROGRESS (sendMessage و callback و Webhook کدنویسی شده؛ تست میدانی باقی است) |
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

F1 و F2 پایه داشبورد هستند. F3 و اتصال فهرست محصول به منوهای موجود در F4 راه ارائه کاتالوگ پویا را باز می‌کنند. F5 و F6 **موازی و روی یک Core مشترک** اجرا می‌شوند؛ هیچ قابلیتِ یک کانال بدون تست هم‌ارز کانال دیگر پذیرفته نمی‌شود. F7 و F8 تنها بعد از تعیین نوع محصول و روش واقعی پرداخت تکمیل می‌شوند. F9 از ابتدا به‌صورت افزایشی اعمال می‌شود.

## مواردی که نباید ناآگاهانه حذف شوند

- داده‌های `Item`، `Buy`، `BuyItem` و `Review` قبلی، تا تهیه Migration و تأیید انتقال داده.
- قابلیت‌های legacy پرداخت رمزارز یا Multibot بدون Feature Flag / داده‌برداری؛ از UI جدید پنهان شوند اما حذف ناگهانی انجام نشود.
- تاریخچه سفارش و تراکنش‌های پرداخت.
