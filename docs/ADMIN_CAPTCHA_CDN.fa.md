# CAPTCHA و CDN اختیاری برای داشبورد Next.js

این قابلیت در شاخهٔ `feat/captcha-turnstile-recaptcha-optional-cdn-20261103`
قرار دارد. محدودهٔ فعلی حفاظت CAPTCHA صفحهٔ Login داشبورد مدیریتی
است؛ Bot Handlerها و Webhookهای Telegram و Bale جریان مستقلی دارند.

## انتخاب CAPTCHA

مقدار `NEXT_ADMIN_CAPTCHA_PROVIDER` را از میان گزینه‌های زیر انتخاب کنید:

| مقدار | رفتار |
|---|---|
| `none` | پیش‌فرض؛ ورود بدون CAPTCHA، با CSRF و Rate Limit موجود |
| `turnstile` | Cloudflare Turnstile |
| `recaptcha_v2` | Google reCAPTCHA v2 Checkbox |
| `recaptcha_v3` | Google reCAPTCHA v3 Score-based |

نمونه در `dashboard-next/.env.local` یا فایل خصوصی
`.env.next-admin` برای Docker Compose:

```dotenv
NEXT_ADMIN_PUBLIC_ORIGIN=https://admin.example.com
NEXT_ADMIN_CAPTCHA_PROVIDER=turnstile
NEXT_ADMIN_CAPTCHA_SITE_KEY=YOUR_PUBLIC_SITE_KEY
NEXT_ADMIN_CAPTCHA_SECRET_KEY=YOUR_PRIVATE_SECRET_KEY
NEXT_ADMIN_RECAPTCHA_V3_MIN_SCORE=0.5
```

در Google باید کلیدهای مختص نسخهٔ v2 یا v3 استفاده شود. مقدار
`NEXT_ADMIN_RECAPTCHA_V3_MIN_SCORE` فقط برای v3 است؛ مقدار پیش‌فرض
۰٫۵ و بازهٔ معتبر صفر تا یک است. hostname واقعی داشبورد
(`NEXT_ADMIN_PUBLIC_ORIGIN`) را در پنل Provider مجاز کنید.
در Codespaces hostname آدرس Forwarded باید مورد پذیرش Provider باشد.

Turnstile بدون Reverse Proxy یا CDN کلادفلر نیز کار می‌کند؛
وجود Cloudflare در مسیر وب‌سایت الزامی نیست.

### Codespaces

در فایل خصوصی `.codespaces/live.env`، این موارد را اضافه یا
ویرایش کنید:

```dotenv
LIVE_ADMIN_CAPTCHA_PROVIDER=turnstile
LIVE_ADMIN_CAPTCHA_SITE_KEY=YOUR_PUBLIC_SITE_KEY
LIVE_ADMIN_CAPTCHA_SECRET_KEY=YOUR_PRIVATE_SECRET_KEY
LIVE_ADMIN_RECAPTCHA_V3_MIN_SCORE=0.5
LIVE_ADMIN_CDN_URL=
```

در نسخهٔ قبلی Codespaces، نبودن این متغیرها معادل حالت پیش‌فرض
`none` است. فایل را با مجوز ۰۶۰۰ و بدون Git Commit نگه دارید و
پس از تغییر، سرویس Dashboard را با تنظیمات جدید Recreate کنید.
هیچ Secretای نباید با پیشوند `NEXT_PUBLIC_` منتشر شود.

## سیاست امنیت و خطا

ترتیب ورود: **CSRF Challenge → Verify CAPTCHA روی Next.js Server →
احراز هویت Staff با FastAPI**. Secret فقط روی سرور موجود است.

سرور موفقیت Siteverify، hostname، و برای Turnstile و reCAPTCHA v3
مقدار `action=login` را بررسی می‌کند. v3 به‌علاوه امتیاز را با
حداقل تعریف‌شده مقایسه می‌کند. Tokenهای ردشده در مرورگر Reset
می‌شوند. اگر Provider قطع باشد، پاسخ معیوب یا timeout شود یا تنظیمات
فعال ناقص باشد، ورود متوقف می‌شود (fail-closed). هیچ تغییر خودکار
از یک Provider به Provider دیگر وجود ندارد.

CSRF فعلی و Rate Limiting ورود حذف نشده‌اند. CAPTCHAs تنها به صفحهٔ
وب Login متصل‌اند؛ هیچ تغییر در درگاه پرداخت، Webhookها یا فایل‌های
خصوصی رسانه اعمال نشده است.

## CDN اختیاری

فایل‌های استاتیک و عمومی خروجی `/_next/static/` را می‌توان
با CDN HTTPS ارائه کرد. بدون تنظیم CDN، همان فایل‌ها مستقیم از
Next.js سرو می‌شوند.

```dotenv
# اختیاری؛ فقط در زمان Build خوانده می‌شود.
NEXT_ADMIN_CDN_URL=https://cdn.example.com
```

این مقدار باید **Origin کامل HTTPS بدون path، query و slash انتهایی**
باشد؛ تنظیم نادرست باعث خطای Build می‌شود. در Compose عادی،
متغیر `NEXT_ADMIN_CDN_URL` را در محیط فراخوانی Build یا
`.env` پروژه قرار دهید: صرف قراردادن آن در `.env.next-admin`
به‌علت Build-time بودن `assetPrefix` کافی نیست.
در Codespaces از `LIVE_ADMIN_CDN_URL` استفاده کنید.

قبل از فعال‌سازی، محتویات `dashboard-next/.next/static/` را از
**همان Build** به مسیر `https://cdn.example.com/_next/static/`
منتقل کنید، یا CDN را به همان مسیر Origin متصل کنید. فایل‌های
Hashشده را با Content-Type درست و Cache-Control مناسب سرو کنید.
اگر Assetها روی CDN موجود نباشند، بخش‌هایی از UI بارگذاری نمی‌شوند؛
در این وضعیت تنظیم CDN را حذف و مجدداً Build کنید.

نکات امنیتی و فنی:

- CDN فقط برای دارایی‌های عمومی Build است؛ `/api`، `/login`،
  Cookie و Session و Private Preview از Origin داشبورد باقی می‌مانند.
- Preview فایل‌های خصوصی `Cache-Control: private, no-store` دارد.
- `assetPrefix` در Next.js فایل‌های داخل `public/` را به‌صورت
  خودکار به CDN منتقل نمی‌کند.
- اسکریپت‌های Turnstile و Google از URL اصلی ارائه‌دهنده دریافت
  می‌شوند؛ آن‌ها را در CDN پروژه ذخیره یا Reverse Proxy نکنید.
- در صورت استفاده از CSP، `https://challenges.cloudflare.com` را
  برای Turnstile و `https://www.google.com` و
  `https://www.gstatic.com` را برای Google، همراه با Origin CDN
  و Directiveهای متناسب مجاز کنید.

## تست و وضعیت پذیرش

```bash
cd dashboard-next
npm run typecheck
npm run lint
npm run test:captcha
npm run build
```

تست‌های `test:captcha` با Mock Siteverify اجرا می‌شوند؛ به
کلید واقعی و شبکهٔ خارجی نیاز ندارند. بررسی‌های Offline پایتون نیز
در `tests/test_captcha_cdn_source_offline.py` اضافه شده‌اند.

برای پذیرش واقعی، تست Browser روی دامنهٔ نهایی با Site Key و
Secret واقعی هر Provider الزامی است. وجود کد و تست‌های Offline
به معنی تأیید Live CAPTCHA یا CDN Production نیست.

## مستندات رسمی

- Cloudflare: https://developers.cloudflare.com/turnstile/get-started/
- Google reCAPTCHA: https://developers.google.com/recaptcha/docs/verify
- Next.js CDN assetPrefix: https://nextjs.org/docs/app/api-reference/config/next-config-js/assetPrefix
