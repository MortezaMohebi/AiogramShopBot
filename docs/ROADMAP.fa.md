# نقشه راه اجرایی Fork

معنی وضعیت‌ها: `DONE` = کد Merge/تست‌شده؛ `IN PROGRESS` = پیاده‌سازی ناقص؛ `PLANNED` = نیازمند توسعه و تست. وجود یک مدل یا رابط در شاخه توسعه به معنی آمادگی Production نیست.

| فاز | خروجی قابل آزمون | وضعیت در شروع Fork |
|---|---|---|
| F0 | اهداف، معماری و معیارهای پذیرش مکتوب | DONE (documentation) |
| F1 | داشبورد SQLAdmin فارسی و RTL، منو/فرم/Modalهای فارسی | CODED (بررسی بصری به مرحله آخر موکول شده) |
| F2 | محصول/دسته‌بندی مستقل، آپلود امن، رضایت، تنظیمات فروشگاه و CRUD | CODED (Migration، اجرای Bot و آزمون واقعی باقی است) |
| F3 | Media upload، Preview و ارسال فایل به هر دو Adapter؛ Cache شناسه فایل | CODED (Cache تفکیک‌شده و سقف فایل اضافه شد؛ تست عملی باقی است) |
| F4 | منوی اصلی ثابت با متن فارسی؛ دکمه‌های کاتالوگ و جزئیات محصول از دیتابیس | PLANNED (بدون Menu Builder؛ صرفاً اتصال Catalog به Handlerهای موجود) |
| F5 | Telegram Adapter، اتصال کاتالوگ و حالت Direct/Proxy/Cloudflare Worker؛ Polling اختیاری | IN PROGRESS (پیاده‌سازی ثبت شد؛ تست Cloudflare و Aiogram واقعی باقی است) |
| F6 | Bale Adapter هم‌زمان با Telegram، Webhook و API | IN PROGRESS (sendMessage و callback و Webhook کدنویسی شده؛ تست میدانی باقی است) |
| F7 | Cart چندقلمی، Coupon، ارسال، Snapshot و تاریخچه سفارش مشترک | CODED (ثبت درخواست بدون پرداخت؛ settlement مالی و تست باقی است) |
| F8 | پرداخت مشترک Telegram Fiat/Stars/Bale، Receipt، تسویه اتمیک و پرونده Refund | CODED (سورس و آزمون‌های Offline ثبت شدند؛ تست Provider و استقرار باقی است) |
| F9 | RBAC و Multi-admin با حساب مستقل و نشست قابل ابطال | IN PROGRESS (کد نقش‌ها/Bootstrap اضافه شد؛ تست امنیت باقی است) |
| F10 | اعتبار داخلی ریالی و Referral مستقل از رمزارز | CODED (Ledger/Reward/Refund کدنویسی شد؛ تست عملی باقی است) |
| F11 | Campaign اختیاری، Broadcast کنترل‌شده و گزارش‌های دوکاناله | CODED (Outbox/داشبورد/آمار ثبت شد؛ تست تحویل باقی است) |
| F12 | تست عملی، Migration، Recovery، Backup، مانیتورینگ و بار | PLANNED (طبق تصمیم پروژه در مرحله نهایی) |

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

## گزارش فاز ۲

[گزارش پیاده‌سازی، وضعیت Wallet و فاصله با برابری قابلیت‌ها](PHASE2_STATUS.fa.md)

## گزارش فاز ۳

[سبد خرید و سفارش مشترک؛ محدوده و موارد باز](PHASE3_SHARED_CHECKOUT.fa.md)

## گزارش فاز ۴

[معماری پرداخت، بازپرداخت و شرایط ایمنی پیش از فعال‌سازی](PHASE4_PAYMENTS.fa.md)

## گزارش فاز ۵

[اعتبار داخلی، Referral، ارسال اختیاری و RBAC](PHASE5_ENGAGEMENT.fa.md)

## مستند برابری قابلیت‌ها — فاز ۵

[اعتبار داخلی، Referral، Broadcast و Analytics](PHASE5_PARITY.fa.md)

## فاز ۶ — فایل‌ها، Webhook و Broadcast

- Bale multipart: عکس ۱۰ MB، سایر فایل‌ها ۵۰ MB؛ قبل از Upload و Send کنترل می‌شود.
- Cache مستقل `file_id` برای هر Bot و Platform در `shop_remote_files`.
- ثبت `update_id` جدا برای Webhook تلگرام و بله، با `needs_review` در خطای نامشخص.
- Broadcast متن و چندرسانه‌ای از SQLAdmin، Batch ده‌نفری و رضایت صریح.
- Bale Business API به‌عنوان حالت هزینه‌دار اختیاری؛ فقط `file_id`، Flag پولی خاموش.
- [گزارش، راه‌اندازی و آزمون‌های لازم فاز ۶](PHASE6_MEDIA_BROADCAST.fa.md)

| فاز | خروجی | وضعیت |
|---|---|---|
| F13 | محدودیت فایل بله، Cache شناسه‌ها و دریافت Webhook بدون تکرار | CODED (Test/Debug نهایی باقی است) |
| F14 | Broadcast متن/رسانه به هر دو Bot، Bale Standard/Business | CODED (بسته به Flag، اجرای واقعی غیرفعال) |

## فاز ۷ — تکمیل Broadcast خودکار

- [x] Worker مشترک و پایدار با صف PostgreSQL برای تمام مخاطبان Opt-in.
- [x] کنترل نرخ مستقل Telegram، Bale Standard و Bale Business، به‌همراه سقف ۱ پیام/ثانیه در هر چت.
- [x] ذخیره وضعیت ارسال و مراحل متن/رسانه بعد از هر پیام؛ بدون Retry خودکار برای Unknown.
- [x] Pause، Resume، Cancel و رسیدگی مستند به پیام‌های نامشخص در داشبورد.
- [x] قفل درخواست‌های پولی Business API با سقف دقیق تأییدشده مدیر و بودجه غیرقابل افزایش در حین اجرا.
- [x] Heartbeat Worker و نمایش درصد پیشرفت/تعداد گیرنده‌های ارسال‌شده.
- [x] سرویس `broadcast-worker` اختیاری در Docker Compose؛ بدون ایجاد Container جدا برای هر مخاطب.
- [ ] اجرای واقعی و تست PostgreSQL / API در مرحله نهایی.

[راهنمای فاز ۷، معماری Durable، تنظیمات و معیارهای پذیرش](PHASE7_DURABLE_BROADCAST.fa.md)
