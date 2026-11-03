# راه‌اندازی واقعی Telegram + Bale + Next.js در GitHub Codespaces

این نسخه از **شاخهٔ** `feat/codespaces-live-stack-20261103` و فایل
`compose.codespaces.yml` استفاده می‌کند. برخلاف محیط تست Mock،
**همان `run.py`، Handlerهای تلگرام و بله، FastAPI، SQLAlchemy، PostgreSQL 18،
Redis و پنل Next.js** اجرا می‌شوند. ارتباط واقعی Bot API برقرار می‌شود،
اما فعال‌سازی پرداخت یا Broadcast پولی بخشی از این راه‌اندازی نیست.

## ۱. ساخت Codespace

۱. در GitHub مخزن `MortezaMohebi/AiogramShopBot` را باز کن.
۲. شاخهٔ `feat/codespaces-live-stack-20261103` را انتخاب کن.
۳. از **Code → Codespaces → Create codespace on branch** وارد محیط شو.
۴. ترجیحاً دستگاه **۴ هسته / ۱۶ گیگابایت RAM** یا بیشتر را انتخاب کن.
   در Codespace کوچک‌تر (۲ هسته/۸ گیگابایت)، Setup تصاویر Python و Next.js
   را **ترتیبی** می‌سازد و Image Python بین Bot و Migration مشترک است؛
   سرعت پایین‌تر است ولی مصرف هم‌زمان حافظه محدود می‌شود.
۵. مطمئن شو Docker Compose V2 فعال است: `docker compose version`.

فایل `.devcontainer/devcontainer.json` پایتون ۳٫۱۲، Docker-in-Docker
و Forward Portهای ۳۰۰۰ و ۸۰۸۰ را آماده می‌کند. در اولین ساخت ممکن است
دریافت Imageها و Dependencyها به اینترنت نیاز داشته باشد.

## ۲. توکن‌های واقعی (ترجیحاً بات‌های اختصاصی تست)

در Telegram از `@BotFather` و در Bale از `@botfather` توکن یک
ربات دریافت کن. بهتر است هر دو **بات تازهٔ تست** باشند؛ زیرا ثبت
Webhook جدید برای باتی که هم‌اکنون در Production فعال است، مسیر دریافت
آپدیت‌های همان بات را به Codespace منتقل خواهد کرد.

بهترین روش ذخیره‌سازی، GitHub **Settings → Codespaces → Secrets** است؛
دو Secret با نام‌های دقیق `TELEGRAM_BOT_TOKEN` و `BALE_BOT_TOKEN`
ایجاد کن و دسترسی مخزن را بده. Codespaces را پس از اضافه‌کردن Secretها
Restart کن. اگر Secret تعریف نکردی، دستور `init` هر دو را از طریق
ورودی مخفی ترمینال درخواست می‌کند.

**توکن را داخل Git Commit، Pull Request، پیام ChatGPT، Screenshot یا
`.env` اصلی قرار نده.** ابزار setup، Secretها را فقط در
`.codespaces/live.env` با مجوز فایل ۶۰۰ نگهداری می‌کند؛ این پوشه
در Git و Docker Build نادیده گرفته می‌شود.

## ۳. نصب و اجرای Docker Compose

در ترمینال همان Codespace:

```bash
git checkout feat/codespaces-live-stack-20261103

# راه‌اندازی تعاملی، گرفتن هر دو Token و تولید Secretها/رمز مدیریت.
bash scripts/setup_codespace.sh init

# چک کردن Compose بدون اجرای سرویس
bash scripts/setup_codespace.sh config

# Build، PostgreSQL، Alembic migration، Redis، Bot و Next.js
bash scripts/setup_codespace.sh start

# دستور مدیریت Visibility پورت‌ها (یا تنظیم دستی در PORTS)
bash scripts/setup_codespace.sh ports

# بررسی اتصال API هر دو پیام‌رسان بدون ارسال پیام
bash scripts/setup_codespace.sh doctor

# اختیاری: محصولات نمایشی واقعی در دیتابیس برای /catalog
bash scripts/setup_codespace.sh demo

# ثبت Webhookها، با تأیید صریح REGISTER
bash scripts/setup_codespace.sh connect
```

**پنل مدیریتی**:

```text
https://<CODESPACE_NAME>-3000.<GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN>/login
```

این URL با متغیرهای واقعی Codespace محاسبه و در خروجی `init`
نمایش داده می‌شود. برای مشاهده آدرس نیاز به حدس زدن نام Codespace نیست.

## ۴. تنظیم پورت‌ها، مهم‌ترین مرحله

در زبانه **PORTS** در محیط Codespace:

| پورت | Visibility | کاربرد |
|---|---|---|
| `3000` | **Private** | داشبورد Next.js، Login، Upload، Finance، Staff |
| `8080` | **Public** | تنها ورودی Webhook تلگرام و بله |
| `5000` | **Expose داخلی Docker** | FastAPI، بدون نشر در Codespaces |
| `5432` / `6379` | **داخلی Docker** | PostgreSQL و Redis |

دستور معادل با GitHub CLI:

```bash
gh codespace ports visibility 8080:public 3000:private -c "$CODESPACE_NAME"
```

برای پورت ۸۰۸۰ در تنظیمات Ports پروتکل داخلی را **HTTP** بگذار؛
آدرس عمومی Forward‌شده توسط خود GitHub با **HTTPS** ارائه می‌شود.
اگر پورت Public را روی **HTTPS protocol** داخلی تنظیم کنی،
GitHub ممکن است Visibility آن را به Private تغییر دهد.

**دقت امنیتی:** هرگز پورت ۳۰۰۰، ۵۰۰۰، ۵۴۳۲ یا ۶۳۷۹ را Public نکن.
Gateway با Nginx فقط `POST /hooks/telegram` و
`POST /webhooks/bale/{secret}` را به Backend می‌فرستد.
آدرس‌های `/admin`، `/internal/admin/v1` و پرداخت‌ها از Gateway
عمومی قابل‌دسترسی نیستند.

## ۵. احراز هویت داشبورد و رمز اولیه

setup به‌شکل امن یک حساب واقعی با Role = `superadmin` می‌سازد.

```text
Username: shopadmin
Password: a different cryptographically random password per Codespace
```

رمز قابل حدس/پیش‌فرض وجود ندارد. هنگام `init` رمز اولیه یک‌بار
در ترمینال خصوصی تو نمایش داده می‌شود؛ برای دیدن دوباره در همان
Codespace:

```bash
bash scripts/setup_codespace.sh credentials
```

**چرا رمز روی صفحه Login یا Dashboard نشان داده نمی‌شود؟** هر بازدیدکننده
نباید بتواند رمز مدیر را ببیند. Password واقعی در PostgreSQL به‌شکل
Hash Argon2 ذخیره می‌شود؛ داشبورد پس از ورود به `/staff` اجازهٔ
تغییر رمز و مدیریت نقش را دارد. اگر رمز را بعداً از داخل پنل تغییر
دهی، مقدار ذخیره‌شدهٔ اولیه در فایل setup دیگر معتبر نیست. رمز فعلی
از Hash قابل بازیابی نیست.

## ۶. اتصال واقعی تلگرام و بله

در `start` بات اصلی راه‌اندازی و با API Telegram احراز هویت می‌شود؛
اما در حالت Codespaces **هیچ Webhook موجودی خودکار جایگزین یا حذف
نمی‌شود**. دستور `doctor` فراخوانی‌های `getMe` و بررسی وضعیت
Webhook را انجام می‌دهد.

`connect`، بعد از تأیید، آدرس‌های زیر را در پیام‌رسان‌ها ثبت می‌کند:

```text
Telegram:
https://<CODESPACE_NAME>-8080.<domain>/hooks/telegram

Bale:
https://<CODESPACE_NAME>-8080.<domain>/webhooks/bale/<random-secret>
```

Telegram از هدر `X-Telegram-Bot-Api-Secret-Token` استفاده می‌کند
و بله از مسیر دارای Secret تصادفی. در Gateway لاگ دسترسی (حاوی
مسیر Secret بله) خاموش است. آپدیت‌ها بر اساس هویت هر بات و
`update_id` به‌شکل Idempotent در PostgreSQL ثبت می‌شوند.

در این مرحله، **دریافت و پاسخ دادن به پیام واقعی** پس از ثبت Webhook
قابل آزمایش است. به هر بات در گفتگوی خصوصی `/start` یا
`/catalog` بفرست. فروشگاه مشترک از همان مدل‌های جدید استفاده می‌کند. برای مشاهدهٔ دو کالای
منتشرشدهٔ نمونه، دستور اختیاری `demo` را قبل از تست اجرا کن؛ این دستور
هیچ دریافت‌کننده، پرداخت یا Broadcast مصنوعی نمی‌سازد.
برای تلگرام اگر عکس پروفایل/Media ID نداری، صفحهٔ شروع از پاسخ متنی
استفاده می‌کند؛ برخی منوهای تصویری قدیمی به تصویر معتبر نیاز دارند.

### مسیر جایگزین تلگرام از ایران

`TELEGRAM_API_MODE` با مقدار `direct` شروع می‌شود. اگر در Codespace
یا شبکهٔ مقصد اتصال مستقیم Telegram API ناموفق بود، Transport فعلی
پروژه همچنین `http_proxy` و `cloudflare_worker` را پشتیبانی می‌کند.
پس از بررسی تنظیمات پروکسی/Worker و Secret اختصاصی، در فایل خصوصی
`.codespaces/live.env` مقادیر زیر را به تناسب تنظیم کن:

```dotenv
LIVE_TELEGRAM_API_MODE=cloudflare_worker
LIVE_TELEGRAM_WORKER_URL=https://YOUR-EXISTING-WORKER-DOMAIN
LIVE_TELEGRAM_WORKER_SECRET=YOUR-RELAY-SECRET
LIVE_TELEGRAM_PROXY_URL=
```

فایل را در Git Commit نکن. سپس `start` و `doctor` را تکرار کن.
API بله از `https://tapi.bale.ai` مستقل از پروکسی تلگرام است.

## ۷. تست‌ها و محدودهٔ ایمنی

```bash
# اجرای Python regression tests بدون ارسال پیام واقعی
bash scripts/setup_codespace.sh test

# مشاهدهٔ سرویس‌ها و وضعیت سلامت
bash scripts/setup_codespace.sh status

# دیدن لاگ Backend و Next.js، بدون چاپ کردن Tokenها
bash scripts/setup_codespace.sh logs
```

`compose.codespaces.yml` سرویس‌های زیر را دارد: PostgreSQL 18،
Redis، Migration، Backend اصلی، Dashboard، Nginx Gateway، Pytest و
**Broadcast Worker اختیاری** در Profile `broadcast`.

در راه‌اندازی اولیه فلگ‌های زیر خاموش هستند:
`SHOP_BROADCAST_WORKER_ENABLED`، `SHOP_CAMPAIGN_DISPATCH_ENABLED`،
`BALE_BROADCAST_PAID_ENABLED`، `BALE_WALLET_CHECKOUT_ENABLED`،
`TELEGRAM_STARS_CHECKOUT_ENABLED` و Refund. در نتیجه تست ارتباط
و پیام عادی، برخلاف تسویهٔ واقعی، هزینه یا ارسال انبوه ایجاد نمی‌کند.
از فعال‌سازی پرداخت و ارسال پولی تا تست Provider واقعی و تأیید
مستقل خودداری کن.

فایل‌های عکس برای هر دو پیام‌رسان از محدودیت محافظه‌کارانهٔ
۱۰ MB و سایر فایل‌ها تا ۵۰ MB تبعیت می‌کنند. درگاه Nginx عمومی
فقط برای JSON آپدیت است؛ آپلود ۵۰ MB از **پورت خصوصی ۳۰۰۰**
و مسیر Next.js انجام می‌شود.

## ۸. توقف، تغییر Webhook و وضعیت Codespace

```bash
# پیش از توقف، Webhookهایی که هنوز به همین Codespace اشاره دارند
# را با تأیید صریح قطع کن.
bash scripts/setup_codespace.sh disconnect

# سرویس‌ها را با حفظ PostgreSQL و فایل‌های تست خاموش کن.
bash scripts/setup_codespace.sh stop

# فقط اگر می‌خواهی همهٔ Volumeهای اختصاصی این Codespace حذف شوند:
bash scripts/setup_codespace.sh reset --yes
```

در برخی نسخه‌های API بله، `getWebhookInfo` وجود ندارد؛ در این
صورت قطع خودکار Webhook بله به‌خاطر خطر حذف Webhook سرور دیگری
انجام نمی‌شود و باید تنظیمات آن بات را دستی بررسی کنی.

GitHub Codespaces ممکن است پس از Restart یا Recreate، پورت Public
را دوباره Private کند. پس از هر Restart، Visibility پورت‌ها و
`doctor` را کنترل کن. اگر نام Codespace تغییر کند، به‌جای تغییر
بی‌صدا درگاه یک بات واقعی، محیط مجزا را به‌طور آگاهانه راه‌اندازی کن.

**وضعیت پذیرش:** فایل Docker و اسکریپت‌ها در GitHub پیاده‌سازی
شده‌اند اما در این جلسه دسترسی اجرایی به Docker Codespace تو وجود
نداشته و `docker compose up`، Migration واقعی، Build و تست
پیام‌رسان هنوز اجرا نشده‌اند. تا PASS شدن چرخهٔ تست/دیباگ،
این شاخه برای Production تأیید نمی‌شود.
