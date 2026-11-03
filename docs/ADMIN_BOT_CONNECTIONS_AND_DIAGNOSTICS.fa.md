# اتصال تلگرام/بله، روش دریافت و تشخیص خطای داشبورد

این نسخه روی شاخه `feat/codespaces-live-stack-20261103` قرار دارد.

## تغییرات

- **CAPTCHA/CDN** از شاخه
  `feat/captcha-turnstile-recaptcha-optional-cdn-20261103` با حفظ
  اصلاحات RTL Login ادغام شده‌اند. CAPTCHA اختیاری است.
- **ذخیره اطلاعات فروشگاه** با `POST /api/admin/shop-settings`
  به‌جای یک Next Server Action مبهم انجام می‌شود؛ API ابتدا
  CSRF Challenge و نشست/نقش اصلی را بررسی می‌کند، بعد
  `PATCH /internal/admin/v1/settings` را با HMAC به FastAPI می‌فرستد.
  پس از ثبت، یک `GET` واقعی از همان جدول `shop_settings`
  خوانده می‌شود و فقط در صورت تأیید مقادیر، پیام «ذخیره شد» نمایش
  داده می‌شود. خطای نشست/مجوز/اعتبارسنجی/سرویس جداگانه نمایش
  داده می‌شود و Request ID برای بررسی در لاگ موجود است.
- صفحهٔ **اتصال ربات‌ها** در `/bot-connections` مخصوص
  `superadmin` شامل وضعیت Telegram/Bale، آدرس Telegram Webhook،
  روش فعلی `webhook` یا `getUpdates`، Transport فعلی
  (`direct`، `http_proxy`، `cloudflare_worker`) و
  بررسی زندهٔ `getMe`/`getWebhookInfo` است.
  مسیر محرمانهٔ Bale عمداً ماسک می‌شود.
- Bale فعلاً فقط Webhook Receiver در این پروژه دارد؛
  `getUpdates` آن به‌عنوان قابلیت پیاده‌سازی‌شده تبلیغ نمی‌شود.

## تغییر روش دریافت Telegram از پنل

Telegram یک بات را هم‌زمان روی Webhook و Long Polling پشتیبانی نمی‌کند.
از این رو کلیک پنل صرفاً **درخواست تغییر حالت** را در Redis ذخیره
می‌کند و سراغ حذف Webhook، Restart یا جابه‌جایی پیام‌ها نمی‌رود.

۱. در `/bot-connections` روش `Webhook` یا
   `getUpdates — Long Polling` را انتخاب و «ثبت درخواست»
   را بزن.
۲. سپس در ترمینال خصوصی Codespace:
   ```bash
   bash scripts/setup_codespace.sh apply-bot-mode
   ```
۳. متن `APPLY` را برای تأیید Restart بنویس.
   این فرمان فقط تنظیم خصوصی `LIVE_TELEGRAM_UPDATE_MODE`
   را تغییر می‌دهد، سرویس `app` را Recreate می‌کند،
   و پس از Healthy شدن درخواست Pending را پاک می‌کند.
۴. اگر به Webhook برگشتی، ثبت Provider را بعد از تنظیم
   درست پورت 8080 از طریق `connect` جداگانه تأیید کن.

هیچ عملگر خودکاری `drop_pending_updates=true` نمی‌فرستد.
بله با Webhook خود مستقل از حالت دریافت تلگرام کار می‌کند.
در Codespace فقط یک Replica برای Receiver در نظر گرفته شده؛
برای چند Replica یا Production باید هماهنگ‌کنندهٔ Durable جدا
طراحی شود.

**تغییر آدرس میزبان Webhook، Proxy URL یا Worker URL**
در این نسخه از طریق فایل خصوصی Deployment و Restart
انجام می‌شود؛ صفحه فقط تنظیم مؤثر را نمایش می‌دهد.
این محدودیت عمدی است تا یک درخواست داشبورد نتواند
آپدیت‌های بات را به URL دلخواه مهاجم منتقل کند.

## «داده‌ها در دسترس نیستند» مساوی قطعی PostgreSQL نیست

FastAPI و Next.js دو سرویس مختلف‌اند و بینشان HMAC وجود دارد.
خطا ممکن است از نشست ابطال‌شده، Clock Skew، عدم تطابق
`NEXT_ADMIN_BRIDGE_SECRET`، خطای `/overview` یا
`/settings`، و نه لزوماً SQL باشد.

عیب‌یابی تفکیکی (فقط Codespace و فقط Read-only):

```bash
git pull --ff-only origin feat/codespaces-live-stack-20261103

bash scripts/setup_codespace.sh start
bash scripts/setup_codespace.sh dashboard-probe

docker compose --env-file .codespaces/live.env \\
  -f compose.codespaces.yml logs --tail=100 app dashboard
```

`dashboard-probe` از رمز مدیر، پیام‌رسان یا سرویس پرداخت
استفاده نمی‌کند؛ با HMAC داخلی واقعی و `SELECT 1` این
چهار درخواست را می‌سنجد:

```text
GET /auth/me
GET /overview
GET /settings
GET /referral-policy
```

اگر SQL PASS ولی `/overview` FAIL باشد، خطا در
Query/مجوز/امضای آن Endpoint است، نه دلیلی قطعی بر
قطع PostgreSQL. اگر همه PASS باشند ولی مرورگر
هنوز خطا دهد، باید Next.js Server Component،
Session Cookie، Server Actions و مرورگر بررسی شوند.

## تست و پذیرش

```bash
bash scripts/setup_codespace.sh build-dashboard
bash scripts/setup_codespace.sh start
bash scripts/setup_codespace.sh auth-smoke
bash scripts/setup_codespace.sh dashboard-probe
```

در Lab ایزوله و با `LAB_ADMIN_PASSWORD`،
`tests/browser/shop-settings.spec.ts` ذخیره، Refresh و
بازگرداندن مقدار قبل را آزمایش می‌کند؛
`tests/browser/bot-connections.spec.ts` نمایش تنظیمات
و ممنوعیت درخواست Anonymous را پوشش می‌دهد.
این آزمون‌ها نباید روی دیتابیس واقعی مشتری اجرا شوند.

**پذیرش نهایی منوط به Build و Browser/DB Debug در Codespace است.**
ادغام سورس، معادل موفقیت تست Live نیست.
