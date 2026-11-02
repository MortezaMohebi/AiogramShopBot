# بررسی‌های لازم پیش از Merge

- [x] Fork و مجوز Write در GitHub تأیید شد.
- [x] شاخه جدا از master ایجاد شد.
- [x] قالب SQLAdmin فارسی/RTL، صفحه ورود فارسی و عنوان‌های مدل‌ها ثبت شدند.
- [x] ساختار SQLAlchemy محصولات، رسانه‌ها و رضایت‌ها اضافه شد؛ Menu Builder از محدوده و مدل‌ها حذف شد.
- [x] Migration غیرمخرب روی جداول جدید تعریف شد.
- [x] کنترل خواندن فایل‌های ثبت‌شده از Branch با GitHub انجام شد.
- [ ] اجرای واقعی `alembic upgrade head` روی دیتابیس موقت.
- [ ] اجرای `pytest` و تست Integration؛ در محیط فعلی اجرا نشده است.
- [ ] بازبینی بصری RTL روی مرورگر، موبایل و فرم‌های SQLAdmin.
- [x] فایل اصلی خصوصی، فرم Upload با CSRF و Preview امن در کد ثبت شد.
- [ ] ارزیابی واقعی MIME، امنیت، آپلود ۲۰ MiB و نمایش در هر دو ربات.
- [ ] اتصال منوی ثابت Telegram به Catalog Service برای نمایش محصولات/رضایت‌ها از دیتابیس (بدون Menu Builder).
- [x] دو Transport مستقل Telegram و Bale و قرارداد مشترک در `channels/` ثبت شد.
- [x] Endpoint بله با Secret و مسیر کاتالوگ تلگرام در کد ثبت شد.
- [ ] تست واقعی Webhook و Callback و اتصال API هر دو پلتفرم.
- [x] حالت Cloudflare Worker همراه با Secret Header، پروکسی فایل و Polling اختیاری در کد ثبت شد.
- [x] پنج Smoke Test محلی Node روی نمونه هم‌منطق Worker PASS شد؛ **Suite اصلی Commit‌شده در Cloudflare اجرا نشده است**.
- [ ] اجرای تست Python برای `CloudflareWorkerSession`، اجرای Node Suite از مخزن و تست Worker واقعی با Token آزمایشی.
- [ ] تست امنیت و صحت اجرای هم‌زمان و جلوگیری از آپدیت تکراری.
- [x] مدل ریال صحیح و ادغام Native Bale Wallet با استعلام مستقل، Order Lock و کاهش اتمیک موجودی در کد ثبت شد.
- [ ] انجام تست واقعی پرداخت، Shipping/Cart/Coupon و RBAC؛ Wallet به‌صورت پیش‌فرض غیرفعال است.

**هشدار:** این PR برای Merge مستقیم در Production آماده نیست. کد قدیمی سفارش/سبد خرید و منوی اصلی عمداً باقی مانده تا Migration داده و جریان خرید با تست انجام شود. فیلدهای `storage_key` فعلاً مسیر فایل هستند، نه رابط Upload واقعی.
