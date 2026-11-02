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
- [x] Cart مشترک، تعداد، Coupon، نشانی/هزینه ارسال و OrderLine به صورت کد ثبت شد.
- [x] ثبت درخواست بدون پول، checkout_key، تاریخچه/لغو و بررسی مدیریتی CSRF+Audit ثبت شد.
- [ ] اجرای Offline testهای `tests/test_shared_cart.py` و تست هم‌زمانی در PostgreSQL.
- [ ] اجرای واقعی پرداخت، Shipping/Cart/Coupon و RBAC؛ Wallet به‌صورت پیش‌فرض غیرفعال است.

**هشدار:** این PR برای Merge مستقیم در Production آماده نیست. کد قدیمی سفارش/سبد خرید و منوی اصلی عمداً باقی مانده تا Migration داده و جریان خرید با تست انجام شود. فایل‌ها از فرم مدیریت در حافظه خصوصی ذخیره می‌شوند، ولی صحت اجرا/امنیت و نمایش آن‌ها هنوز عملیاتی تأیید نشده است.

## فاز ۴: کنترل‌های پرداخت

- [x] Intent یکتای فاکتور، تمایز IRR و XTR، قیمت مستقل Stars و Flagهای خاموش ثبت شد.
- [x] Telegram `pre_checkout_query` و `successful_payment` به تسویه مشترک وصل شدند.
- [x] Bale `inquireTransaction` پیش از تسویه پرداخت مشترک اجرا می‌شود؛ مسیر Legacy حفظ شد.
- [x] قفل Order/محصول/Coupon، مصرف یک‌باره تخفیف و Receipt تکراری در سورس طراحی شد.
- [x] پرونده Refund، مسیر رسمی Stars و تأیید دستی Provider در داشبورد ثبت شد.
- [x] فایل Unit/Offline `tests/test_shared_payment_settlement.py` در مخزن ثبت شد.
- [ ] اجرای `pytest`، Migration و تست هم‌زمانی واقعی PostgreSQL.
- [ ] آزمایش Telegram Stars، Provider IRR تلگرام، کیف پول بله و بازپرداخت واقعی با Sandbox.
- [ ] تأیید نرخ/ریزواحد IRR در Provider منتخب و تکمیل فرآیند Reconciliation پس از Timeout.

## فاز ۵: قابلیت‌های مشترک غیررمزارزی

- [x] دفترکل IRR با تراکنش‌های یکتا و حساب‌های تفکیک‌شده برحسب پیام‌رسان در کد ثبت شد.
- [x] امکان پرداخت و برگشت اعتبار فروشگاه بدون استفاده از Crypto یا کیف پول شخصی بله نوشته شد.
- [x] سیاست و کدهای Referral و پاداش یک‌باره پس از پرداخت IRR معتبر نوشته شد؛ سیاست پیش‌فرض خاموش است.
- [x] Opt-in/Opt-out برای ارسال اطلاعیه، Campaign و Outbox با Batch محدود و بدون Retry کورکورانه نوشته شد.
- [x] گزارش RTL با آمار مستقل Telegram/Bale و تفکیک IRR، XTR و Store Credit در کد ثبت شد.
- [x] حساب‌های Staff و Roleهای مجزا با رمز Argon2، ابطال نشست و محدودیت دسته‌ای SQLAdmin نوشته شد.
- [x] تست‌های Offline فاز ۵ در `tests/test_shop_engagement.py` ثبت شدند؛ **اجرا نشده‌اند**.
- [ ] اجرای تست‌ها، Migrationهای `20261102d001` و `20261102d002` و بررسی مرورگر و امنیت واقعی.
- [ ] بررسی ضدتقلب Referral، اعلان ناشناخته، Revocation و عدم ارسال پس از Opt-out.
- [ ] اجرای سناریوی کامل Telegram/Bale شامل پرداخت و دریافت/بازگشت اعتبار روی PostgreSQL آزمایشی.
