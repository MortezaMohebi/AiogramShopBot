# سیاست خطا و ورود داشبورد Next.js — Telegram + Bale

## علت مشکل

فرم قبلی `/login` به‌صورت Native HTML به `/api/auth/login`
ارسال می‌شد. کنترل سخت‌گیرانهٔ هدر `Origin` در Reverse Proxy
Codespaces پیش از بررسی رمز، پاسخ خام `403 Forbidden` می‌داد.
ناتوانی در ورود لزوماً نشانهٔ نامعتبر بودن رمز مدیر نبود.

## مسیر جدید احراز هویت

```text
Browser /login (فارسی RTL)
  |
  | GET /api/auth/challenge
  v
Next.js -> random 32-byte challenge
        -> HttpOnly + Secure + SameSite=Strict + host-only cookie
  |
  | POST /api/auth/login (JSON, same-origin)
  | x-shop-login-challenge: value
  v
Next.js -> compare cookie with header in constant time
        -> Fetch Metadata / cross-site check
        -> bounded 4 KiB body + validate username/password
        -> signed HMAC request to FastAPI
  |
  v
FastAPI -> Redis login throttle -> Argon2 ShopStaff
  |
  +--> 401 invalid_credentials: inline UI, clear rejected password
  +--> 429 temporarily_locked: inline UI
  +--> 503 service_unavailable: inline UI
  +--> 403 security_check_failed: inline UI + reload link
  +--> network timeout: inline UI, no raw error details
  |
  +--> 200: Secure HttpOnly staff session cookie
             -> full navigation to /dashboard
```

کوکی Challenge ده دقیقه عمر دارد و برای هر تلاش تازه تجدید می‌شود.
کوکی دارای پیشوند `__Host-` روی Production تعریف می‌شود؛
دامنهٔ همسایه نمی‌تواند آن را جعل کند. Browser فقط مقدار Challenge
را از JSON same-origin می‌خواند، نه خود کوکی HttpOnly را.
هیچ Endpoint ناامن برای دریافت رمز مدیر ایجاد نشده است.

## پیام‌های مورد انتظار

| وضعیت | عنوان فارسی | رفتار |
|---|---|---|
| 401 | ورود انجام نشد | نمایش پیام، پاک‌کردن رمز ردشده، حفظ نام کاربری |
| 403 | بررسی امنیتی ورود ناموفق بود | نمایش پیام و لینک بازکردن دوبارهٔ Login |
| 429 | تلاش‌های ورود بیش از حد مجاز است | پیام محدودیت تلاش، بدون افشای جزئیات داخلی |
| 422 | اطلاعات ورود ناقص است | اعتبارسنجی مرورگر و سرور |
| 503 | سرویس ورود در دسترس نیست | پیام قابل بازیابی، بدون جزئیات زیرساخت |
| اختلال شبکه | ارتباط با سرور قطع شد | ماندن در Login و پیشنهاد تلاش مجدد |
| موفقیت | انتقال به داشبورد | Refresh کامل برای خواندن Cookie تازه |

هر پاسخ خطا دارای Code ثابت و Request ID تصادفی است؛ تنها
Code و شناسهٔ پیگیری در سرور لاگ می‌شود، بدون Password، توکن،
Header محرمانه یا Stack Trace. نسخهٔ قدیمی فرم که در Tab قبلی
باز مانده است به `/login?error=security_check_failed` هدایت می‌شود
و دیگر صفحهٔ خام Forbidden نشان نمی‌دهد.

## پوشش خطا در بخش‌های دیگر

- Logout از همان Challenge امن و پیام خطای درون منو استفاده می‌کند.
- Upload اگر در بررسی Origin/Fetch Metadata شکست بخورد، به همان
  صفحه با `?error=security` برمی‌گردد؛ حجم، نوع فایل و RBAC
  پیام‌های جداگانه دارند.
- `app/error.tsx` برای خطای Route و
  `app/global-error.tsx` برای خرابی Root Layout، صفحهٔ خطای
  فارسی با دکمهٔ تلاش دوباره و لینک Login نمایش می‌دهند.
- `app/(console)/error.tsx` برای درخواست‌های داشبورد از قبل وجود دارد.
- فرم‌های حساس مالی همچنان نتیجهٔ مبهم Provider را به معنای
  موفقیت نمی‌گیرند؛ نباید هنگام خطای نامشخص، بازپرداخت یا پرداخت
  را بدون بررسی تکرار کرد.

## آزمون در Codespaces

```bash
git pull --ff-only origin feat/codespaces-live-stack-20261103
bash scripts/setup_codespace.sh build-dashboard
bash scripts/setup_codespace.sh start
bash scripts/setup_codespace.sh auth-smoke
```

`auth-smoke` فقط با یک حساب ناموجودِ کاملاً تصادفی و
درخواست‌های محلی کار می‌کند؛ هیچ رمز `shopadmin` و هیچ
Bot APIای را استفاده نمی‌کند.

انتظار: سه `PASS` برای ردّ POST بدون CSRF، دریافت Challenge
و رسیدن POST با `Origin: null` به Backend (401 برای حساب
ناموجود یعنی موفقیت تست امنیت و Route).

تست اختیاری مرورگر:
`tests/browser/auth-login.spec.ts` شامل حالت Login نامعتبر،
خطای سرویس، خطای CSRF و بازشدن مستقیم API است. اجرای این
آزمون نیازمند Playwright و محیط مرورگر سالم است.

## وضعیت پذیرش

این تغییر در شاخهٔ Draft است. Build جدید و آزمون‌های واقعی
روی Codespace باید انجام شوند؛ هنوز هیچ PASS اجرایی برای نسخهٔ
تغییریافته از سمت محیط واقعی دریافت نشده است. برای سایر
فرم‌های مدیریتی، تعمیم خطاهای قابل بازیابی در مراحل بعدی
قابل انجام است و نباید پوشش جزئی فعلی را با پذیرش کامل اشتباه گرفت.
