# اتصال Telegram Bot API با Cloudflare Worker

این قابلیت **اختیاری** است و به بله وابستگی ندارد. برای ساخت Worker از نمونه آزمایشی
کاربر الهام گرفته شده، ولی نسخه این مخزن یک Relay دارای احراز هویت است و Open Proxy نیست.

## سه حالت API تلگرام

| Mode | نحوه اتصال |
|---|---|
| `direct` | Aiogram مستقیماً به `api.telegram.org` متصل می‌شود |
| `http_proxy` | از `TELEGRAM_PROXY_URL` به عنوان HTTP/SOCKS Proxy استفاده می‌کند |
| `cloudflare_worker` | درخواست‌های API و دانلود فایل از Worker قابل‌تنظیم عبور می‌کنند |

متدهای Bot API در Worker Hard-coded نیستند؛ مسیرهای مجاز `/bot<TOKEN>/<METHOD>` و
`/file/bot<TOKEN>/<PATH>` به شکل داینامیک به **فقط** `api.telegram.org` ارسال می‌شوند.
آپلود با `multipart/form-data` و دانلود فایل‌ها به‌صورت Stream انجام می‌شود.
هیچ Cache یا CORS عمومی برای پاسخ‌های دارای اطلاعات ربات فعال نیست.

## راه‌اندازی Worker

ابتدا در یک حساب Cloudflare Worker بسازید. سورس این Worker در
`cloudflare/telegram-relay/src/index.mjs` موجود است؛ راه دیگر نصب Wrangler و اجرای:

```bash
cd cloudflare/telegram-relay
npx wrangler login
npx wrangler secret put RELAY_SHARED_SECRET
npx wrangler deploy
```

مقدار `RELAY_SHARED_SECRET` را با Secret تصادفی حداقل ۳۲ کاراکتری ایجاد کنید.
برای ساخت امن در محیط خودتان می‌توانید از
`python -c "import secrets; print(secrets.token_urlsafe(48))"` استفاده کنید.
**Secret و Token ربات را در Git، گفتگو یا متن مستندات قرار ندهید.**

گزینهٔ `wrangler.toml` یک نام نمونه دارد؛ نام Worker و دامنه‌اش قابل تغییر است.
آدرس Worker می‌تواند `*.workers.dev` یا دامنه اختصاصی HTTPS باشد؛ کد Python
فقط از طریق `TELEGRAM_WORKER_URL` آن را می‌شناسد و به دامنه خاصی وابسته نیست.
آدرس باید **Origin بدون مسیر** باشد.

## تنظیمات ربات در VPS

```env
TELEGRAM_API_MODE=cloudflare_worker
TELEGRAM_WORKER_URL=https://your-worker.your-account.workers.dev
TELEGRAM_WORKER_SECRET=<SAME_SECRET_AS_CLOUDFLARE>
# Optional: polling requires no publicly accessible Telegram webhook
TELEGRAM_UPDATE_MODE=polling
TELEGRAM_PROXY_URL=
```

برای حالت مستقیم:
```env
TELEGRAM_API_MODE=direct
TELEGRAM_UPDATE_MODE=webhook
```

برای SOCKS/HTTP Proxy:
```env
TELEGRAM_API_MODE=http_proxy
TELEGRAM_PROXY_URL=socks5://127.0.0.1:1080
```

**تفاوت API Mode و Update Mode:**

- `TELEGRAM_API_MODE` مسیر ارتباط خروجی Aiogram با Bot API است.
- `TELEGRAM_UPDATE_MODE=webhook` یعنی پیام‌ها مستقیماً از Telegram به `WEBHOOK_URL`
  سرور می‌رسند. Cloudflare Worker این مسیر را خودکار تغییر نمی‌دهد و سرور همچنان
  به HTTPS عمومی قابل دسترس نیاز دارد.
- `TELEGRAM_UPDATE_MODE=polling` یعنی دریافت پیام‌ها نیز از طریق
  `getUpdates` روی **همان API Mode** انجام می‌شود. برای یک VPS که فقط
  اتصال خروجی به Worker دارد، معمولاً انتخاب ساده‌تری است.
- به دلیل انحصاری بودن روش‌های دریافت Telegram، در Polling ابتدا Webhook
  قبلی با `deleteWebhook` حذف می‌شود.
- حالت Legacy `MULTIBOT=true` فعلاً فقط Webhook را پشتیبانی می‌کند.

بله همچنان از `BaleTransport` و Webhook مستقل خودش استفاده می‌کند. اگر بله
از همین VPS ارائه می‌شود، endpoint بله باید از شبکه بله قابل دسترس باشد.

## مرزهای امنیتی

- Worker **تنها** به `https://api.telegram.org` درخواست می‌زند؛ آدرس Host
  یا URL دلخواه کاربر نمی‌تواند مقصد را تغییر دهد.
- متدهای HTTP و مسیرها محدود هستند: `GET/POST` برای API، فقط `GET` برای فایل.
- همه درخواست‌ها نیازمند هدر `X-Telegram-Relay-Key` با Secret مستقل از Bot Token هستند.
- Secret در Cloudflare Secrets و در متغیر محیطی سرور نگهداری می‌شود؛
  به Telegram، CDNهای دیگر یا درخواست‌های دانلود خارجی ارسال نمی‌شود.
- Redirectهای خارجی Follow نمی‌شوند؛ Worker خطای امن و بدون Token برمی‌گرداند.
- هنگام Deploy، Worker logs و Reverse Proxy logs باید فاقد Bot Token در URL باشند.
- در حالت Production، ارتباط VPS با HTTPS Worker را تست کنید؛ ممکن است دامنه
  `workers.dev` در بعضی شبکه‌ها قابل دسترس نباشد. دامنه اختصاصی راه‌حل قطعی
  برای همه مسیرهای شبکه نیست.
- Worker جلوی سوءاستفاده از API در صورت افشای کلید یا Bot Token را به‌تنهایی
  نمی‌گیرد؛ Rate Limit، Rotation و مانیتورینگ باید مستقل اجرا شوند.
- هنگام تغییر `TELEGRAM_WORKER_URL` یا Mode، متغیرهای محیطی را اصلاح و
  Bot Service را Restart کنید؛ **تغییر سورس یا Deploy جدید ربات لازم نیست**.

## بررسی بدون توکن واقعی

```bash
cd cloudflare/telegram-relay
node --test test/relay.test.mjs
cd ../..
pytest -q tests/test_telegram_worker_session.py
```

در نهایت لازم است روی VPS واقعی یک آزمایش اتصال `getMe` و `getUpdates` یا
`setWebhook` انجام شود. این تست‌ها را بدون توکن آزمایشی معتبر نمی‌توان PASS کرد.


## مدیریت از پنل Next.js (جدید)

برای تغییر مسیر خروجی **بدون ویرایش دستی `TELEGRAM_API_MODE` در هر تغییر**،
پس از تعیین مقصدهای مجاز در Deployment به
**اتصال ربات‌ها → مسیر API تلگرام** بروید. Direct، HTTP/SOCKS5 Proxy و
Cloudflare Worker از جریان ثبت پیشنهاد، تست `getMe` و تأیید رمز/MFA
پشتیبانی می‌کنند. وضعیت موفق در PostgreSQL رمزنگاری‌شده می‌ماند و پس از
Restart بارگذاری می‌شود. Broadcast Worker نیز نسخهٔ تأییدشده را دریافت می‌کند.

جزئیات امنیت، Allowlist، Recovery، Rollback و تست‌های پذیرش:
[`docs/TELEGRAM_TRANSPORT_DASHBOARD.fa.md`](./TELEGRAM_TRANSPORT_DASHBOARD.fa.md).

از این مسیر هیچ Token یا مقدار `RELAY_SHARED_SECRET` در GitHub،
پاسخ GET، لاگ یا Query String ثبت نکنید. مواردی مانند تغییر Token
یا ایجاد Worker در Cloudflare همچنان نیازمند مجوزها و تنظیمات مستقل‌اند.
