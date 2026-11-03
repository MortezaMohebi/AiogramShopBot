# راهنمای مدیریت Direct / Proxy / Cloudflare Worker از پنل

**شاخه:** `feat/staff-security-invites-mfa-audit-20261103`  
**صفحه:** `Dashboard → اتصال ربات‌ها → مسیر API تلگرام`  
**وضعیت:** تغییرات Source ثبت شده‌اند؛ تست زندهٔ Telegram/Worker، Docker و مرورگر Codespace هنوز تأیید نشده است. PR #5 باید Draft باقی بماند.

## دامنه

- Telegram outbound Bot API: `direct`، `http_proxy` (HTTP CONNECT یا SOCKS5) و `cloudflare_worker`.
- Cloudflare Worker فقط در مسیر خروجی Telegram Bot API استفاده می‌شود؛ مسیر Bale و گردش‌کار جداگانهٔ Webhook/getUpdates را تغییر نمی‌دهد.
- Token ربات همان `TOKEN` موجود در Deployment است و از پنل دریافت/ذخیره/نمایش/تعویض نمی‌شود.
- تنظیمات آخرین وضعیت تأییدشده در `shop_telegram_transport` و پیشنهاد/تاریخچه در `shop_telegram_transport_changes` است.
- تنها یک پیشنهاد فعال مجاز است؛ پیشنهادهای دیگر تا تعیین تکلیف رد می‌شوند.
- Redis همچنان مسئول Rate Limit تلاش‌های `probe/apply` و احراز هویت است.
- رمز Proxy و Relay Key داخل یک JSON با Fernet و کلید `SHOP_SECURITY_ENCRYPTION_KEY` رمز می‌شوند؛ هیچ credential در Git، HTML پیش‌نمایش، Audit، GET یا URL مرورگر بازگردانده نمی‌شود.

## چرا Allowlist لازم است؟

Worker و Proxy به Bot Token دسترسی شبکه‌ای پیدا می‌کنند؛ یک URL دلخواه می‌تواند Token را سرقت کند. مدیر فقط از میان مقصدهای **قبلاً مورد اعتماد در Deployment** انتخاب می‌کند. ابتدا در محیط سرور اصلی یا در `.codespaces/live.env` مقدار مقصدهای مجاز را ثبت کنید:

```dotenv
# آدرس‌های غیرمحرمانه؛ جداشده با کاما:
LIVE_TELEGRAM_PROXY_ALLOWED_ENDPOINTS=http://proxy.example.net:3128,socks5://proxy.example.net:1080
LIVE_TELEGRAM_WORKER_ALLOWED_ORIGINS=https://your-relay.example.net

# در صورت وجود، تنظیمات قبلی همچنان به‌عنوان مقصد مجاز پذیرفته می‌شوند:
LIVE_TELEGRAM_API_MODE=direct
LIVE_TELEGRAM_PROXY_URL=
LIVE_TELEGRAM_WORKER_URL=
```

در Production نام متغیرها بدون پیشوند `LIVE_` است: `TELEGRAM_PROXY_ALLOWED_ENDPOINTS` و `TELEGRAM_WORKER_ALLOWED_ORIGINS`. دو Allowlist فقط شامل endpointهای مجاز **بدون Username/Password** هستند. مقصدهای خصوصی یا لوکال تنها در صورتی مجازند که Deployment مشخصاً همان Proxy Endpoint را Allowlist کرده باشد؛ Worker همیشه HTTPS و hostname غیرمحلی لازم دارد.

برای ایجاد Worker از سورس امن `cloudflare/telegram-relay/` استفاده کنید. `RELAY_SHARED_SECRET` را در Cloudflare تنظیم کنید؛ Relay Key متناظر را **فقط در فرم محرمانهٔ پنل** وارد کنید. آدرس Worker باید فقط HTTPS Origin، بدون Path، Query، Fragment و Userinfo باشد. کلید حداقل ۳۲ نویسه دارد.

## گردش‌کار دقیق

۱. در پنل، حالت Direct / Proxy / Cloudflare Worker را انتخاب کنید. برای Proxy یک Endpoint مجاز و در صورت نیاز Username/Password وارد کنید. برای Worker یک Origin مجاز و Relay Key وارد کنید. اگر همان endpoint فعال باقی بماند، خالی‌گذاشتن Secret به معنی حفظ نسخهٔ رمزنگاری‌شدهٔ فعلی است.

۲. **ثبت پیشنهاد**: داده‌ها اعتبارسنجی و رمزنگاری شده و رکورد `pending` ایجاد می‌شود؛ مسیر زنده تغییر نمی‌کند. شمارهٔ نسخه `expected_version` در برابر تغییرات هم‌زمان کنترل می‌شود.

۳. **تست اتصال جدید**: یک Session ایزوله از مسیر پیشنهادی با همان Token موجود `getMe` را فراخوانی می‌کند؛ اگر شناسهٔ بات با هویت تأییدشده متفاوت باشد رد می‌شود. این مرحله هیچ تنظیم زنده یا Webhook را تغییر نمی‌دهد.

۴. **تأیید هویت و فعال‌سازی**: مالک `superadmin` رمز و MFA را ارائه می‌کند. وضعیت `applying` پیش از اتصال خارجی در PostgreSQL ثبت می‌شود. Session جدید `getMe` را تست می‌کند، Session مدیریت‌شده تا اتمام درخواست‌ها و فایل‌های درحال‌ارسال صبر کرده و مسیر جدید را فعال می‌کند. سپس نسخهٔ جدید در DB ذخیره و رکورد `succeeded` می‌شود. در شکست ایمن، Session قبلی برمی‌گردد و رکورد `failed` می‌شود.

۵. **بازیابی/بازگشت**: گزینهٔ «پیشنهاد بازگشت» فقط رکورد جدید `pending` با تنظیمات قبلاً تأییدشده ایجاد می‌کند. فعال‌سازی بازگشت نیز نیازمند مرحلهٔ ۳ و ۴ است. هیچ بازگشت خودکار مبهم و هیچ `drop_pending_updates` وجود ندارد.

۶. **نتیجه نامشخص**: اگر سرور وسط Apply قطع شود، رکورد `needs_review` پس از راه‌اندازی علامت‌گذاری می‌شود. عملیات قبلی خودکار تکرار نمی‌شود. گزینهٔ «تطبیق بدون تکرار تغییر» فقط وقتی مسیر زنده واقعاً با نسخهٔ تأییدشدهٔ DB برابر باشد و `getMe` همان بات را بازگرداند، درخواست نامشخص را تعیین‌تکلیف می‌کند.

## اجرای چندپردازشی

- پردازشگر اصلی FastAPI باید همان فرایندی باشد که Bot Session مدیریت‌شده و `ConnectionSupervisor` را نگه می‌دارد. از اجرای چند Receiver مستقل استفاده نکنید؛ Supervisor در PostgreSQL مالکیت Receiver را با Advisory Lock کنترل می‌کند.
- Broadcast Worker فرایند جدا دارد. قبل از Claim هر گیرنده و قبل از هر گام ارسال، آخرین نسخهٔ تأییدشده را از PostgreSQL خوانده و در صورت تغییر، Session مستقلش را با `getMe` تأیید و جایگزین می‌کند. یک تغییر ناموفق ارسال را به وضعیت مبهم می‌برد، نه تکرار خودکار.
- در راه‌اندازی مجدد، فقط نسخهٔ **موفق و ثبت‌شده** بازیابی می‌شود، نه پیشنهاد `pending`.
- از کارافتادن Proxy یا Worker نباید صفحهٔ بازیابی مدیر را از دسترس خارج کند. Probe اولیهٔ Telegram با خطای امن ثبت می‌شود و پنل برای پیشنهاد مسیر جایگزین فعال می‌ماند.
- `Bale` و `Telegram Webhook/getUpdates` مستقل هستند. درگاه‌ها، توکن‌ها، مانده‌ها، سفارش‌ها و صف Update تغییر داده نمی‌شوند.

## Migration و امنیت

پس از پشتیبان‌گیری از PostgreSQL، روی Production با Alembic نسخهٔ `20261103o001` پس از `20261103n001` نصب می‌شود؛ هیچ `DROP` یا `ALTER` روی جدول‌های قبلی انجام نمی‌شود. در Codespaces، `scripts.security_bootstrap` ایجاد افزایشی دو جدول را با بررسی Schema انجام می‌دهد؛ Reset یا پاک‌کردن Volumeها مجاز نیست.

کلید `SHOP_SECURITY_ENCRYPTION_KEY` را پس از Restart تغییر ندهید، مگر اینکه برای رمزنگاری دوبارهٔ همهٔ داده‌های MFA و تنظیمات Transport روی نسخهٔ بکاپ‌دار برنامهٔ مهاجرت کلید وجود داشته باشد.

## آزمون پذیرش (الزامی پیش از Merge)

```bash
pytest -q tests/test_telegram_transport_control_offline.py
pytest -q tests/test_telegram_worker_session.py tests/test_telegram_utils.py
pytest -q
cd dashboard-next
npm run typecheck
npm run lint
npm run build
```

در Codespace با PostgreSQL واقعی و Tokenهای تستِ مختص همین Codespace، **بدون فعال‌کردن پرداخت یا ارسال واقعی** این موارد باید PASS شوند:

- Stage به هر سه Mode، رد URL نامعتبر/غیرمجاز، Secret کمتر از حداقل، حفظ رمز قبلی در همان endpoint.
- Test `getMe` از Worker/Proxy آزمایشی بدون تغییر مسیر فعال، تست Worker با Secret اشتباه و دریافت خطای امن.
- Apply با MFA صحیح، رمز اشتباه، MFA تکراری، تست Session قدیمی درحال پردازش و وضعیت نسخه بعد از Commit.
- Restart سرویس اصلی و Broadcast Worker؛ هر دو از نسخهٔ فعال در PostgreSQL استفاده کنند.
- قطع شبکهٔ Worker، بازشدن پنل بازیابی، Stage و Apply مسیر Direct پس از بازگشت دسترسی.
- Rollback پیشنهادی، تأیید هویت، `needs_review` ناشی از قطع کنترل‌شده، Reconcile بدون تکرار درخواست.
- عدم نمایش Token، Relay Key و Proxy Password در HTML، پاسخ API، Docker logs، Headerهای GET و جدول Audit.
- Webhook/getUpdates، Update offsets، وضعیت سفارش‌ها و کیف پول‌ها پس از تغییر Transport ثابت بمانند.
- Playwright در RTL و موبایل، واکنش فرم، خطاهای دسترسی و Refresh وضعیت را بررسی کند.

**این تست‌ها در این گفتگو به‌صورت عملی اجرا نشده‌اند و نباید به‌عنوان PASS گزارش شوند.**
