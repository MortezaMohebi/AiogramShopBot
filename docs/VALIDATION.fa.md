> Historical implementation record. Current runtime and setup: [Registry-only](REGISTRY_ONLY_RETIREMENT.md) and [README](../readme.md).

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

## بازبینی تکمیلی فاز ۵ (Source-only)

- [x] صفحه گزارش یکپارچه به `services/shop_analytics.py` متصل شده تا ریزواحد پرداخت تلگرام، قیمت ریالی و Stars با هم جمع نشوند.
- [x] صفحه اول داشبورد لینک‌های مدیریتی را با Role و مجوز ModelView فیلتر می‌کند.
- [x] دفترکل Referral فقط با تأیید واقعی رکورد Provider به اعتبار معرف پاداش می‌دهد.
- [x] ابزار `scripts/reconcile_shop_referrals.py` با حالت Dry-run و `--apply` صریح در مخزن موجود است.
- [x] Startup از `create_all()` برای ساخت جداول مالی صرف‌نظر می‌کند و Alembic Head را الزام می‌کند.
- [x] پیش‌فرض ثبت SQL Parameters غیرفعال است.
- [x] فایل‌های تست مکمل برای Analytics، Campaign Opt-in و Wallet/Referral به مخزن اضافه شدند.
- [ ] اجرای تمامی تست‌های مخزن و کنترل خطاهای احتمالی، طبق تصمیم پروژه در مرحله نهایی.
- [ ] تأیید کامل اتصالات Telegram/Bale، CORS/CSRF/Auth داشبورد، Migration و Reconciliation روی DB آزمایشی.
- [ ] اثبات ظرفیت Rate Limiting، امنیت ارسال‌های Unknown، عدم تکرار Reward و کنترل بازپرداخت واقعی.

## فاز ۵ — قابلیت‌های دوکاناله

- [x] کیف پول داخلی ریالی با Ledger و Idempotency به هر دو کانال در کد متصل شد.
- [x] Referral اختیاری، Consent و Campaign Outbox برای هر دو پیام‌رسان ثبت شد.
- [x] RBAC و صفحه‌های مالی/کمپین/گزارش با کنترل نقش ثبت شدند.
- [x] ارسال واقعی کمپین با `SHOP_CAMPAIGN_DISPATCH_ENABLED=false` به‌صورت پیش‌فرض بسته شد.
- [ ] تست‌های `test_shop_engagement.py` و تست SQLite/PostgreSQL هم‌زمان اجرا شوند.
- [ ] تأیید امنیت و عدم هم‌پوشانی Handlerهای Legacy و مشترک، قبل از Merge.

## فاز ۶ — محدودیت بله، رسانه و Broadcast

- [x] سقف رسمی Bale multipart عکس ۱۰٬۰۰۰٬۰۰۰ و سایر فایل‌ها ۵۰٬۰۰۰٬۰۰۰ بایت در Upload و Transport ثبت شد.
- [x] مسیر OGG صوتی تا ۱ MB به Voice و بزرگ‌تر به Document تغییر می‌کند.
- [x] `ShopRemoteFile` شناسه فایل هر Bot/Platform و نوع ارسال را مجزا ذخیره می‌کند.
- [x] `ShopInboundUpdate` قبل از پردازش، Updateهای تکراری Webhook بله و تلگرام را شناسایی می‌کند.
- [x] کمپین دارای متن، رسانه‌های متعدد و مخاطب Telegram/Bale/All است؛ فقط Opt-in ارسال می‌شود.
- [x] Bale Business Mode هزینه‌دار با Flag مستقل و پیش‌بررسی `file_id` همان بازو ایجاد شد.
- [x] آزمون‌های Offline محدودیت فایل، Media Broadcast، Business API و Dedup در مخزن نوشته شدند.
- [ ] اجرای `pytest`، Alembic و تست آپلود در مرزهای رسمی ۱۰/۵۰ MB.
- [ ] آزمون واقعی Telegram/Bale Webhook، API فایل، Business حساب شارژشده و خطای میان ارسال.
- [ ] بررسی وضعیت‌های `processing` / `needs_review` و `unknown` با شواهد Provider قبل از Retry دستی.
- [ ] اندازه‌گیری Rate Limit و هزینه واقعی Business API قبل از فعال‌کردن Flagهای Broadcast.

**منبع رسمی:** [Bale Bot API](https://docs.bale.ai/) و [گزارش فاز ۶](PHASE6_MEDIA_BROADCAST.fa.md)

## فاز ۷ — Broadcast خودکار تا پایان همه گیرنده‌ها (سورس فقط)

- [x] یک اقدام Start، سرویس مشترک Worker را برای Drain تمام صف فعال می‌کند؛ محدودیت Batch ده‌تایی روی کل کمپین اعمال نمی‌شود.
- [x] وضعیت‌های `sending/paused/needs_review/completed/cancelled` در جداول جدید اضافه شدند.
- [x] Resume صرفاً صف باقی‌مانده را ادامه می‌دهد و ردیف‌های `unknown` را دوباره ارسال نمی‌کند.
- [x] `ShopBroadcastRateSlot` نرخ Bot و هر چت را در PostgreSQL بین Workerها هماهنگ می‌کند.
- [x] `ShopCampaignAudit` و `ShopBroadcastWorkerHeartbeat` برای گزارش و Audit ثبت شدند.
- [x] حالت پولی Bale Business با سقف قابل‌محاسبه و تأیید مستقل، قبل از تک‌تک درخواست‌ها بودجه را رزرو می‌کند.
- [x] GUI فارسی شروع/توقف/ادامه/لغو، درصد پیشرفت و تعیین تکلیف وضعیت `unknown` دارد.
- [x] تست‌های Offline جدید برای ۲۷ گیرنده، Restart، Opt-out، Rate و سقف هزینه به مخزن اضافه شدند.
- [ ] اجرای `pytest` و `alembic upgrade head` روی DB آزمایشی؛ **در این فاز اجرا نشده**.
- [ ] تست PostgreSQL `FOR UPDATE SKIP LOCKED`، Worker هم‌زمان، قطع شبکه، SIGTERM و بازیابی Safe.
- [ ] تست واقعی Rate Limit API تلگرام/بله و هزینه Business پیش از روشن‌کردن Flagها.
- [ ] تأیید هیچ Broadcast واقعی با یک Flag ناقص، یا خارج از رضایت کاربر، صادر نشود.

[گزارش فاز ۷](PHASE7_DURABLE_BROADCAST.fa.md)
