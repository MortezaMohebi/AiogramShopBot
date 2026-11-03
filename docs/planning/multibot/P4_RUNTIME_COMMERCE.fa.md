# P4 — Multi-Bot Runtime & Commerce

**مخزن:** MortezaMohebi/AiogramShopBot
**شاخه:** `feat/multibot-runtime-commerce-20261103` (روی شاخهٔ P3)
**وضعیت سورس:** پیاده‌سازی شده؛ **وضعیت QA:** تست نشده (به درخواست مالک، محیط تست فعلاً در دسترس نیست).

## دامنهٔ پیاده‌سازی

- هر بات تلگرام و بله یک `BotContext` معتبر و سروری دارد. صرف `platform_user_id` یا دادهٔ Callback نمی‌تواند بات را انتخاب کند.
- یک `MultiBotSupervisor` مشترک به‌جای Container جداگانه برای هر بات، مالکیت انحصاری با PostgreSQL advisory lease را اعمال می‌کند؛ هر بات Polling Offset و Receiver مستقل خود را دارد.
- Webhook هر بات به یک `binding_id` تصادفی و Secret رمزنگاری‌شده متصل است. برای تلگرام، هدر `X-Telegram-Bot-Api-Secret-Token` هم بررسی می‌شود.
- API مدیریت Receiver از Stage بدون شبکه و Activate واقعی با Password/MFA مجدد، بررسی getMe و بررسی مالکیت Webhook قبل از تغییر استفاده می‌کند. Timeout نامشخص به `needs_review` می‌رود، نه Retry خودکار.
- مسیر پیام، Catalog، Callback، Cart، Checkout، Payment/Refund، اعتبار فروشگاهی، Referral و Consent از `bot_id` معتبر استفاده می‌کند. وضعیت Maintenance/Paused جلوی فروش جدید را می‌گیرد ولی رسید موفق قبلی همچنان قابل تسویه است.
- فایل‌های Remote و Inbound Receipts از هر بات و از چرخهٔ تعویض Token تفکیک شده‌اند. کلید یکتای Receipt شامل `bot_id` و `update_id` است؛ Offset فقط پس از وجود Receipt پایدار جلو می‌رود.
- UI فارسی Next.js وضعیت Receiver، Mode، Offset، اجازهٔ Runtime و مالکیت Lease را بدون افشای Token یا URL محرمانه نشان می‌دهد و عملیات Stage/Activate را تفکیک می‌کند.

## Migration افزایشی

Migration `20261103s001_multibot_runtime.py` پس از P3 اجرا می‌شود و مالکیت ثابت دو بات Legacy را برای رکوردهای سابق تعیین می‌کند:

- `shop_identities`, `shop_carts`, `shop_orders`, `shop_payment_attempts`, `shop_inbound_updates`, `shop_remote_files` و Slotهای ارسال با `bot_id` مشخص Backfill می‌شوند.
- Wallet/Entry، Referral/Reward، Campaign Delivery از کلید والد مالکیت می‌گیرند؛ کمپین تاریخی مشترک با چند مقصد مجاز است `bot_id=NULL` بماند، اما گیرندگانش مستقل‌اند.
- Uniqueness هویت و Cart از `(platform, platform_user_id)` به `(bot_id, platform_user_id)` تغییر می‌کند؛ Receipt از `(bot_id, update_id)` استفاده می‌کند.
- مهاجرت درصورت فقدان مالک Legacy یا تطبیق‌نداشتن مالکیت Payment و Order، در همان تراکنش متوقف می‌شود. هیچ Balance/Payment/Refund قدیمی حذف یا صفر نمی‌شود.
- Downgrade مخرب ممنوع است. Rollback امن به معنای بازگردانی نسخهٔ کد و حفظ جدول‌های افزایشی تا بررسی سوابق است، نه ادغام دوبارهٔ حساب مشتریان.

## مرزهای مهم و ایمنی

- اجرای Runtime **پیش‌فرض خاموش** است (`MULTIBOT_V2_RUNTIME_ENABLED=false`). برای مسیر Webhook باید `MULTIBOT_WEBHOOK_BASE_URL` یک HTTPS عمومی و معتبر باشد؛ Start/ASGI نیز باید اجرای Receiver زنده را صریحاً مجاز کند.
- مرحلهٔ Stage Provider را تغییر نمی‌دهد. Activate فقط برای Draft تأییدشده و Store پیش‌فرض فعال، با Credential رمزنگاری‌شدهٔ معتبر، Lease سالم، Session مجاز و MFA انجام می‌شود.
- هیچ‌گونه `drop_pending_updates=true`، تغییر خودکار Webhook خارجی، Retry کور در پرداخت/ارسال یا اجرای Provider در زمان ثبت این تغییرات انجام نشده است.
- Worker فعلی Broadcast فقط دو Token قدیمی را دارد. کمپین متعلق به Bot جدید قابل Snapshot شدن است، ولی **شروع ارسال آن تا فاز P5 مسدود است** تا Worker Pool و Credential per-bot آماده شود. این مرز عمداً fail-closed است.
- Store جدید بدون Catalog مستقل و Cutover تاییدشده همچنان نباید در محیط واقعی فروش داشته باشد. این فاز معماری چندباتیِ Store پیش‌فرض را تکمیل می‌کند.
- فاز P5 اتصال و تخصیص چند Worker/Cloudflare، Rate Limit و Secret Rotation چندباتی است؛ P6 پذیرش Migration و Cutover نهایی را اجرا می‌کند.

## چک‌لیست پذیرش معوق (هنوز هیچ موردی PASS نیست)

- [ ] اجرای `pytest -q tests/test_multibot_runtime_offline.py` و مجموعه تست‌های P1 تا P3، سفارش، پرداخت و Broadcast.
- [ ] `alembic upgrade head` روی **کپی** PostgreSQL واقعی؛ تطبیق شمار رکوردهای Identity/Cart/Order/Payment، موجودی کیف پول و وضعیت Refund قبل/بعد و تکرار Bootstrap.
- [ ] اجرای Static TypeScript check، ESLint، Build Next.js، کنترل RBAC/Session/MFA و نمایش صحیح فرم Receiver در Light/Dark و RTL.
- [ ] تست حداقل ۲ Bot تلگرام و ۲ Bot بله با User ID یکسان، Callback قدیمی، Cart مستقل، ACL محصول، شکست شبکه و تغییر Token.
- [ ] بررسی Lease Loss، Restart وسط Polling/Provider Mutation، رسیدهای duplicate، آدرس Webhook مخرب و وضعیت `needs_review` بدون ارسال مجدد.
- [ ] بررسی Checkout واقعی، Precheckout، paid/refunded و Reconciliation هنگام Paused/Disabled، Referral/Wallet و ثبات موجودی.
- [ ] تست E2E آفلاین/Provider، مرور Audit و عدم افشای Token در Logs، URLهای پنل و Bridge.
- [ ] تأیید مالک پروژه برای Cutover؛ سپس روشن‌کردن Feature Flag و انتقال مرحله‌ای پس از دریافت خروجی تست‌ها.

**نتیجه:** P4 به‌عنوان **Source Complete / Acceptance Pending** ثبت می‌شود و تا فراهم‌شدن محیط تست و تأیید صریح مالک، هیچ ادعای Production-Ready یا PASS ندارد.
