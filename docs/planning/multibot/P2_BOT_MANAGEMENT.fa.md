# P2 — مدیریت بات‌ها، وضعیت عملیاتی و تأیید هویت

**Branch:** `feat/multibot-management-20261103`  
**Base:** `feat/multibot-foundation-20261103` (PR #6)  
**State:** Source implemented; Codespaces/PostgreSQL/Provider/Browser acceptance pending.

## دامنهٔ Source

- صفحهٔ جدید `/bots`: فهرست صفحه‌بندی‌شدهٔ بات‌ها، فیلتر Store/Provider، ثبت بات Draft و Store غیرفعال.
- صفحهٔ `/bots/{bot_id}`: تنظیم نام، مسئول، محیط، متن خوش‌آمد و Maintenance، لینک پشتیبانی؛ وضعیت، هویت تأییدشده، نسخهٔ Credential و Audit هر بات.
- دو بات قبلی به‌صورت مستقل وضعیت **Active / Maintenance / Paused / Disabled** دارند. هر تغییر با Version/Role/Recent Reauthentication و Audit انجام می‌شود.
- حالت Pause/Disable در Telegram از Global Aiogram Update Middleware و در Bale از handler ایمن پس از بخش‌های پردازش مالی اعمال می‌شود؛ در Broadcast Worker نیز مانع Claim جدید و ارسال گام بعدی می‌شود.
- پرداخت‌های قبلاً صادرشده، PreCheckout و Successful Payment در هر دو پیام‌رسان همچنان به کد تسویه می‌رسند.
- برای بات‌های جدید، Token فقط به‌صورت نسخه‌بندی‌شده و Fernet-encrypted ذخیره می‌شود. Token خام از مرورگر/Backend GET/Audit/Log بازگردانده نمی‌شود. Fingerprint با HMAC از کلید Secret برای تشخیص ثبت دوباره استفاده می‌شود.
- `verify` فقط `getMe` را از Telegram/Bale اجرا می‌کند؛ `provider_bot_id` و `verified_at` را پس از تأیید و کنترل Version/Unique Identity ثبت می‌کند. **هیچ بات جدیدی فعال نمی‌شود.**
- صفحهٔ اتصال قدیمی فقط برای تنظیم زیرساخت Worker/Proxy/Webhook/getUpdates دو Receiver فعلی نگه داشته شده و کنترل اختصاصی بات از آن جدا شده است.
- گزارش Health از آخرین Update و تعداد Receiptهای `processing/needs_review` می‌آید؛ `getMe` فقط به درخواست کاربر زده می‌شود و نبود Update نشانهٔ Offline اعلام نمی‌شود.
- `20261103q001_bot_operations.py` جدول تنظیمات و چهار ستون Nullable مربوط به Credential Verification را اضافه می‌کند. Codespaces قبلی بدون Reset و با DDL افزایشی و بررسی Schema به‌روزرسانی می‌شود.

## نکات عملیاتی

**این مرحله Multi-Bot Runtime نیست.** تنظیمات صرفاً برای بات‌های Legacy بلافاصله بر مسیر فروش و پیام‌های عادی فعلی اثر می‌کنند. بات جدید `draft` بوده و هیچ Receiver/Payment/Cart/Wallet/Opt-in آن با Legacy ادغام نشده است. بعد از تکمیل فاز چهارم، دکمهٔ واقعی فعال‌سازی بات‌های جدید اضافه می‌شود.

| وضعیت | پیام جدید | Broadcast | پرداخت‌های قبلی |
|---|---|---|---|
| Active | مجاز | مجاز (در حد سیاست ارسال) | رسیدگی |
| Maintenance | پیام نگهداری | توقف Claim و گام جدید | رسیدگی |
| Paused | پیام توقف | توقف Claim و گام جدید | رسیدگی |
| Disabled | پاسخ عادی ندارد؛ Callback تأیید می‌شود | توقف Claim و گام جدید | رسیدگی |

*پشتیبانی از تغییر Token فعال Legacy، حذف Webhook و تغییر مسیر Receiver عمداً در این UI وجود ندارد.* Tokenهای قبلی همچنان از ENV خوانده می‌شوند. تغییر فعالِ امن Credential و خودکار کردن تعدد Receiverها به فاز چهارم وابسته است.

## تست و Debug / Retest

- [x] سورس Backend، Migration، UI و Test Cases در GitHub ثبت شد.
- [ ] `python -m pytest -q tests/test_multibot_management_offline.py`
- [ ] `python -m pytest -q tests/test_multibot_foundation_offline.py`
- [ ] `python -m pytest -q`
- [ ] `npm --prefix dashboard-next run typecheck`
- [ ] `npm --prefix dashboard-next run lint`
- [ ] `npm --prefix dashboard-next run build`
- [ ] Migration `20261103p001` سپس `20261103q001` روی PostgreSQL کپی‌شده از داده‌های موجود؛ تأیید برابری count/amount سفارش، مشتری، سبد و Ledger قبل/بعد.
- [ ] Bootstrap دوباره Codespaces بدون Reset و بدون Duplicate.
- [ ] آزمون دو مرورگر: RBAC/MFA/Recent Reauth/CSRF، خطای نسخه قدیمی، Credential جدید در Draft، Deny Token تکراری، عدم نمایش Secret.
- [ ] آزمون زندهٔ getMe دو بات قدیمی و بات‌های Draft تلگرام/بله؛ هیچ Webhook جدیدی ثبت نشود.
- [ ] توقف و فعال‌سازی مستقل Telegram/Bale و تأیید اینکه دریافت Successful Payment در همهٔ وضعیت‌ها از بین نمی‌رود.
- [ ] Broadcast: Paused نباید صف را مصرف کند؛ جابه‌جایی وضعیت وسط ارسال به شکل کنترل‌شده باعث حفظ receipt و جلوگیری از Retry خودکار شود.
- [ ] Playwright RTL/Mobile با سناریوی خطای Backend.

**GitHub Actions عمداً غیرفعال است.** ابزارهای GitHub این محیط برای اجرای Docker یا فرمان‌های واقعی در Codespace مناسب نیستند؛ هیچ تست عملیاتی در این گفتگو به‌صورت PASS اعلام نشده است.

## مسیر فاز بعدی

**P3 Catalog ACL:** افزودن Many2many قوانین محصول و دسته‌بندی برای هر `bot_id`، سیاست پیش‌فرض Deny برای بات‌های تازه، Allow/Deny با اولویت روشن، UI در Product Editor و Bot Details، و enforcement در Catalog/Media/Callback/Cart/Checkout.

بعد از این فاز و گذر از آزمون‌های P4، تعداد بیشتر Botها به Runtime واقعی متصل می‌شوند؛ P5 به Worker Pool چندباتی اختصاص دارد.
