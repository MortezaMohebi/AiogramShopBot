# محیط تست Docker Compose — ربات تلگرام و بله + Next.js

این محیط مخصوص شاخهٔ `integration/all-prs-20261103` است و از فایل اصلی
`docker-compose.yml`، دیتابیس واقعی، فایل‌های رسانه و توکن‌های
تلگرام/بله استفاده نمی‌کند.

## پیش‌نیاز

- Docker Engine و Docker Compose V2
- Python 3.12 یا نسخهٔ سازگار برای اجرای ابزار راه‌اندازی (فقط Standard Library)
- منابع کافی برای ساخت دو Image پایتون و Next.js، و برای Upload ۵۰ مگابایتی
- اتصال اینترنت **فقط هنگام Build** جهت دانلود Imageها و Dependencyها

## راه‌اندازی

```bash
git checkout integration/all-prs-20261103

# هر بار فقط در اولین راه‌اندازی Secretهای اختصاصی تولید می‌کند.
python3 scripts/test_lab.py init

# بررسی ساختار Compose و جایگزینی متغیرها، بدون استقرار.
python3 scripts/test_lab.py config

# Build Backend و Next.js، اجرای Migrationهای Alembic،
# تولید دادهٔ نمونه و راه‌اندازی HTTPS روی لوپ‌بک.
python3 scripts/test_lab.py up

# تست‌های موجود و سپس Smoke Test روی PostgreSQL/Redis/Next.js واقعی.
python3 scripts/test_lab.py test

# گزارش وضعیت و لاگ‌ها
python3 scripts/test_lab.py status
python3 scripts/test_lab.py logs
```

**نشانی پنل:** <https://localhost:8443/login>

Caddy از گواهی‌نامهٔ `tls internal` استفاده می‌کند. مرورگر در اولین
بازدید احتمالاً به CA داخلی اعتماد ندارد؛ این HTTPS آزمایشی است. هرگز
این CA را به‌عنوان مرجع عمومی یا Production استفاده نکنید. برای بررسی
سادهٔ HTTPS از `curl -k -I https://localhost:8443/login` استفاده کنید.
در صورت نیاز به نصب CA، گواهی‌نامهٔ Root فقط در محیط آزمایشی و مطابق
فرایند اعتماد دستگاه توسعه اضافه شود.

## حساب‌های نمونه

در اولین اجرای `init`، فایل **غیرقابل Commit**
`.env.test.local` ساخته می‌شود که رمزهای متفاوت و تصادفی دارد.
نام‌های کاربری به شرح زیر هستند:

| نام کاربری | نقش |
|---|---|
| `labadmin` | `superadmin` |
| `labcontent` | `content` |
| `labsales` | `sales` |
| `labmarketing` | `marketing` |
| `labfinance` | `finance` |
| `labviewer` | `viewer` |

مقدار `LAB_ADMIN_PASSWORD` متعلق به `labadmin` است و بقیه با نام‌های
`LAB_CONTENT_PASSWORD` و نظایر آن مشخص‌اند. آن‌ها را صرفاً روی دستگاه
توسعه و از فایل محلی بخوانید و در چت، PR یا لاگ منتشر نکنید.

در دیتابیس ایزوله دو محصول آزمایشی، یک سفارش پرداخت‌نشده، دو هویت
ساختگی با **شناسهٔ عددی یکسان ولی پیام‌رسان متفاوت**، یک کمپین Draft،
یک نظر تأییدنشده، روش ارسال و Coupon ساخته می‌شود. داده‌ها به‌صورت
Idempotent درج می‌شوند و اجرای مجدد Seed تغییرات دستی آزمایش را
بازنویسی نمی‌کند.

## سرویس‌ها

| سرویس | وظیفه | درگاه میزبان |
|---|---|---|
| `postgres` | PostgreSQL 18، Volume آزمایشی | ندارد |
| `redis` | Redis رمزدار، Login Throttle | ندارد |
| `migrate` | `alembic upgrade head` + Seed، یک‌بار در راه‌اندازی | ندارد |
| `api` | FastAPI اصلی مدیریت با HMAC و RBAC واقعی؛ بدون Bot Lifecycle | ندارد |
| `next-admin` | Build و اجرای واقعی Next.js | ندارد |
| `caddy` | HTTPS داخلی و Reverse Proxy | فقط `127.0.0.1:8443` |
| `pytest` | اجرای تست‌های Python، در Profile `qa` | ندارد |
| `smoke` | Login، RBAC، HMAC و چرخهٔ Upload/Preview/Publish/Delete | ندارد |

فقط سرویس `caddy` روی میزبان Publish می‌شود. API، PostgreSQL و Redis
صرفاً در شبکهٔ `private` با `internal: true` قابل‌دسترسی‌اند.

### جریان تست

```text
Browser --HTTPS 8443--> Caddy --> Next.js production build
                                    |
                            Session + signed HMAC
                                    |
                                    v
                         FastAPI test-only app
                           (same admin router)
                                    |
                         PostgreSQL + Redis
                                    |
                           private media volume

migrate: Alembic -> sample data -> API can start
pytest: existing tests (isolated)
smoke: HMAC login -> RBAC -> real multipart -> preview -> approve
       -> deny published deletion -> unpublish -> delete test file

NO: bot.py / Telegram polling / Webhooks / external provider payments
NO: real Telegram Stars refund / Bale Business calls / live Broadcast
```

**چرا خود `bot.py` اجرا نمی‌شود؟** Lifecycle برنامهٔ فعلی هنگام
شروع به API تلگرام وصل می‌شود. برای تضمین عدم ارسال درخواست واقعی،
`scripts/test_lab_app.py` فقط Router مدیریتی اصلی را به FastAPI
متصل می‌کند و قبل از Import، همهٔ فلگ‌ها و توکن‌های خارجی را بررسی
و در صورت تنظیم ناامن Fail-Closed می‌کند. این آزمایش یکپارچگی
پنل و Backend است، **نه جایگزین تست نهایی اتصال واقعی ربات‌ها**.

## تست و عیب‌یابی

```bash
# اجرای مجدد فقط Smoke، بدون اجرای تمام unit testها
python3 scripts/test_lab.py smoke

# مشاهدهٔ Migration و Seed در log
docker compose --project-name dual-messenger-shop-lab \
  --env-file .env.test.local -f compose.test.yml logs migrate

# ورود shell فقط در Container تست
docker compose --project-name dual-messenger-shop-lab \
  --env-file .env.test.local -f compose.test.yml exec api sh
```

در Build، Dockerfile مخصوص Node دستورات `typecheck`،
`lint` و `next build` را اجرا می‌کند. تا قبل از افزودن Lockfile
مرور‌شده، از `npm install` استفاده می‌شود؛ پس Build ممکن است به
شبکه دسترسی نیاز داشته باشد و هنوز Deterministic نیست.

تست‌های Smoke خطاهای Auth، اختصاص Role، Redis Throttle،
خواندن دادهٔ واقعی Postgres، فهرست سفارش و Refund و یک Upload
واقعی را بررسی می‌کنند. در Upload، فرمت تصویر با بایت‌های نمونهٔ
بی‌خطر اعتبارسنجی می‌شود و فایل در انتها پاک می‌شود.

## پاک‌سازی

```bash
# خاموش‌کردن، با حفظ داده‌های تست
python3 scripts/test_lab.py down

# حذف کامل Volumeهای فقط همین پروژه (Postgres، Media و CA داخلی)
python3 scripts/test_lab.py reset --yes
```

دستور `reset` نیازمند تأیید صریح است. Secretهای محلی
`.env.test.local` پس از Reset باقی می‌مانند تا اتفاقی وارد مخزن
نشوند؛ برای تولید مجموعهٔ جدید، فایل را فقط پس از Reset کامل به‌صورت
دستی حذف و دوباره `init` کنید.

## معیار پذیرش و مرز تست

- [x] تعریف Compose، Dockerfileها، CA داخلی، Migration و Seed
- [x] جلوگیری از اجرای واقعی Bot/Webhook/Payment/Worker در Lab
- [x] افزودن Test Runnerهای Python و Smoke با RBAC و Upload واقعی
- [ ] **اجرای Docker Compose روی میزبان دارای Docker**، رفع خطاها و تکرار
- [ ] بازبینی Migrationهای PostgreSQL 18 و تست Concurrency واقعی
- [ ] تست مرورگر فارسی RTL، Dark Mode، Keyboard، 320/768/1440
- [ ] تست فایل دقیقاً نزدیک سقف‌های ۱۰ و ۵۰ مگابایت و مصرف حافظهٔ Proxy
- [ ] تولید و Commit کردن `package-lock.json` و تغییر Build به `npm ci`
- [ ] تأیید یکپارچهٔ API واقعی Telegram/Bale با Test Token مستقل،
      **فقط پس از اجازهٔ صریح**

این فایل **Compose تست است، نه Deploy Production**. هیچ PR، Branch اصلی
یا Flag پرداخت و Broadcast تغییر وضعیت اجرایی نمی‌دهد.
