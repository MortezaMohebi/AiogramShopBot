# شاخه مستقل مهاجرت داشبورد به Next.js

**Branch:** `feat/nextjs-rtl-dashboard-20261103`

**پایه:** `feat/fa-rtl-dynamic-catalog-bale-foundation` در Commit
`d07fe3cb46772523c9c8e4fb2ec546b087744934`.

**وضعیت:** پیاده‌سازی سورس در شاخه جدید؛ هیچ Build اجرایی، Migration، استقرار
یا تست واقعی Telegram/Bale انجام نشده است. این تغییر وارد master یا PR#1 نشده.

## تصمیم‌های معماری

- Next.js 16 App Router + React 19 + TypeScript برای UI.
- پالت خنثی با Accent سبز ملایم، Dark Mode، RTL واقعی `lang=fa`،
  فونت محلی Vazirmatn از بسته Fontsource و طراحی Responsive.
- الگوی UI از بلوک‌های shadcn/ui: `dashboard-01` (Overview + KPI +
  Table)، `sidebar-07` (Navigation)، `login-01` (ورود). اجزای
  کپی‌شده به‌صورت محلی در `components/ui` قابل‌توسعه‌اند و
  `components.json` به‌صورت `rtl: true` تنظیم شده است. اجرای CLI
  نصب رسمی بلوک‌ها روی شاخه هنوز انجام نشده است؛ بلوک‌های فعلی پیاده‌سازی
  و بومی‌سازی معادل همان الگوها هستند.
- **FastAPI همچنان تنها Business Core است**. Next.js به PostgreSQL
  مستقیم، مدل کیف پول بله یا API پیام‌رسان‌ها متصل نمی‌شود.
- به‌جای حذف ناگهانی، SQLAdmin قبلی تا پذیرش کامل و تست یکپارچه به‌عنوان
  مسیر اضطراری حفظ می‌شود. عملیات رسانه، Refund و تنظیمات حساس در
  این شاخه به API امضاشدهٔ FastAPI و رابط Next.js منتقل شده‌اند.

### جریان متنی قابل تبدیل به دیاگرام

```text
Browser (HTTPS, Persian RTL)
  |
  | HttpOnly + Secure + SameSite=Strict Staff Cookie
  v
Next.js (one shared dashboard, App Router)
  | Server Components + Server Actions
  | Bounded 50.1 MB same-origin multipart Route Handler
  | Authenticated private binary preview Route Handler
  | HMAC-SHA256(method/path/query/body/staff/version/timestamp)
  v
FastAPI /internal/admin/v1
  | Validate HMAC / expires <=60 sec
  | Revalidate ShopStaff.is_active / role / session_version
  | Use exact existing SQLAlchemy models and services
  +-> PostgreSQL / Redis throttle
  +-> ShopProduct / Category / Order / Coupon / Campaign / Identity
  +-> Existing BroadcastControl + ShopAnalytics
  |
  +-> Legacy SQLAdmin (still available for sensitive workflows)
```

## صفحات اضافه‌شده

| صفحه Next.js | داده/عملیات | مرز دسترسی |
|---|---|---|
| Login | Auth با ShopStaff و Argon2 | عمومی برای ورود، Redis throttle |
| Dashboard | KPI و مقایسه تلگرام/بله، سفارش اخیر در نقش مجاز | تمام کارکنان |
| Products | فهرست، جستجو، افزودن و ویرایش قیمت IRR و Stars، انتشار | content/superadmin |
| Categories | افزودن، ترتیب، ویرایش، انتشار | content/superadmin |
| Orders | مشاهده + قبول/رد امن سفارش Manual بدون Paid | sales/finance برای مشاهده؛ sales برای تصمیم |
| Customers | مشاهده هویت و Opt-in جدا برای هر پیام‌رسان | sales/superadmin |
| Shipping | CRUD هزینه ارسال با عدد صحیح ریال | sales/superadmin |
| Coupons | CRUD درصد/مبلغ، اعتبار، سقف استفاده | marketing/superadmin |
| Campaigns | ایجاد Draft، Approve، Start با سقف هزینه، Pause/Resume/Cancel | marketing/superadmin |
| Campaign Details | Unknown با مدرک، فایل‌های Draft، Upload/Preview/حذف، آماده‌سازی خصوصی بله | marketing/superadmin |
| Reports | درآمد ریالی، Credit و XTR جدا، لیست پرفروش‌ها | تمام کارکنان |
| Settings | نام فروشگاه، پیام خوش‌آمد، FAQ، پشتیبانی و سیاست Referral | superadmin |
| Media | Upload، پیش‌نمایش امن، ویرایش توضیح/ترتیب، تأیید/لغو انتشار و حذف Draft | content/superadmin |
| Reviews | بارگذاری متن/فایل و مدیریت کامل Moderation با پیش‌نمایش خصوصی | content/superadmin |
| Finance | Ledger، اصلاح اعتبار دارای سند و سقف، Refund رسمی Stars/اعتبار داخلی/ثبت مدرک خارجی | finance/superadmin |
| Staff | ساخت/ویرایش کارکنان، نقش، فعال‌سازی، تغییر رمز و ابطال نشست | superadmin |

**مرز وضعیت:** تمام عملیات مدیریتی یادشده در سورس Next.js و Backend پیاده‌سازی
شده‌اند ولی هنوز Build و تست یکپارچهٔ آن‌ها در محیط واقعی اجرا نشده است.
مهاجرت سوابق قدیمی Telegram، استقرار، مدیریت زیرساخت و فعال‌سازی نهایی
درگاه/Worker خارج از این تغییرند. SQLAdmin تا پذیرش کامل حذف نمی‌شود.

## امنیت

- Cookie حاوی Staff ID/Session Version و Expiry با HMAC جداگانه است؛
  هیچ JWT، رمز، توکن درگاه یا Secret Backend به Browser داده نمی‌شود.
- Next.js فقط از Backend روی Docker private network درخواست امضا‌شده
  ارسال می‌کند. امضا شامل Timestamp، Method، Path+Query، SHA256 Body،
  Staff ID و Session Version است.
- FastAPI علاوه بر امضا، فعال‌بودن، نقش واقعی و نسخه Session را
  در هر درخواست از PostgreSQL می‌خواند. حذف/غیرفعال‌سازی/تغییر نقش
  مانع ادامه نشست قبلی است.
- احراز هویت از همان Hashهای Argon2 موجود و Redis Login Throttle
  استفاده می‌کند. API عمومی Next شامل Login/Logout و مسیرهای محدود Upload/Preview است؛
  Upload با Origin دقیق و Session و RBAC و محدودیت کل Body محافظت می‌شود.
  همهٔ عملیات نیز در FastAPI مجدد اعتبارسنجی می‌شوند.
- ️`NEXT_ADMIN_BRIDGE_ENABLED=false` پیش‌فرض و Secret مستقل
  `NEXT_ADMIN_BRIDGE_SECRET` (حداقل ۳۲ نویسه) الزامی است.
- Frontend هنگام شروع بدون Secret کافی یا API غیرقابل‌دسترسی Fail-Closed
  می‌شود؛ داده ساختگی به‌جای Backend نمایش داده نمی‌شود.

## ساختار برنچ

```text
dashboard-next/
  app/
    (auth)/login
    (console)/dashboard, products, categories, orders, customers,
              shipping, coupons, campaigns, reports, settings,
              media, reviews, finance, staff
    api/auth/login, api/auth/logout
    api/admin/upload, api/admin/preview/[kind]/[id]
  components/
    ui/               # shadcn-compatible primitives
    blocks/           # RTL layout, KPI, channel report and table blocks
  lib/
    bridge.ts         # HMAC API client; server-only
    session.ts        # HttpOnly cookie verifier
    types.ts, utils.ts, navigation.ts
  package.json, components.json, Dockerfile, .env.example
dashboard/next_api.py # Internal signed FastAPI bridge + bounded request body
dashboard/next_operations.py # Upload, moderation, finance, staff and admin actions
tests/test_next_admin_bridge.py
tests/test_next_admin_operations_offline.py
```

## استقرار ایزوله (انجام نشده)

```bash
# After final approval and isolated DB migrations:
cp .env.next-admin.example .env.next-admin
cp dashboard-next/.env.example dashboard-next/.env.local

# Use a strong random 32+ char shared secret for both components.
# Set NEXT_ADMIN_BRIDGE_ENABLED=true in the Python bot .env
# and the exact same NEXT_ADMIN_BRIDGE_SECRET in .env.next-admin.
# Use a DIFFERENT NEXT_ADMIN_SESSION_SECRET for the cookie.
# Configure NEXT_ADMIN_PUBLIC_ORIGIN=https://admin.example.com on Next.js.
# Keep upload ingress limit >= 50,100,000 bytes and use HTTPS only.

# Next.js remains opt-in; public Caddy routing is a separate approved step.
docker compose --profile dashboard-next up -d next-admin
```

**HTTPS reverse proxy:** یک Subdomain مستقل مثل `admin.example.com`
فقط به `next-admin:3000` وصل می‌شود؛ توکن داخلی HMAC در هیچ
Client-side Environment Variable قرار نمی‌گیرد. سرویس FastAPI همچنان
روی شبکه Docker قابل‌دسترس است و API عمومی از مسیر HMAC محافظت می‌شود.

این شاخه هیچ نیاز یا وابستگی به Vercel ندارد.

## معیارهای پذیرش نهایی

- [ ] `npm install`، تولید و بررسی `package-lock.json` و جایگزینی
      `npm install` با `npm ci` در Docker پیش از Production.
- [ ] `npm run typecheck`، `npm run lint`، `npm run build`.
- [ ] `pytest -q tests/test_next_admin_bridge.py` و تست اختیارات و
      HMAC، Login Throttle، Replay و Session Revocation با DB واقعی.
- [ ] تست مرورگری ۳۲۰/۷۶۸/۱۴۴۰ پیکسل، فارسی، Dark Mode، RTL،
      تست Keyboard و Screen Reader.
- [ ] تست واقعی CRUD، هم‌زمانی، Back/Forward، فرم‌های خطادار و
      مهاجرت حساب‌های قدیمی بدون انتشار داده مشتری.
- [ ] جلوگیری از درج URL غیرمجاز، SSRF، CSRF، Brute-force و
      افشای Headerها در لایه Proxy.
- [ ] ارزیابی Caddy، HTTPS، Rate Limiting، Log Redaction و Backup.
- [x] پیاده‌سازی سورس Upload، Media، Moderation، Wallet، Referral، Refund،
      Staff، بررسی سفارش و رسانه Broadcast در همین شاخه.
- [ ] اجرای تست SQLite/Database، تست آپلود ۱۰/۵۰ MB و تداخل هم‌زمانی
      قبل از خاموش‌کردن SQLAdmin.
- [ ] عدم اجرای Broadcast/پرداخت واقعی در این مرحله.

**این برنچ یک مرحله توسعه است؛ آماده Merge نهایی، جایگزینی کامل SQLAdmin
یا پذیرش پرداخت واقعی نیست.**

## انتقال عملیات مدیریتی در این شاخه — Source-complete، هنوز QA نشده

| مسیر API داخلی | مجوز | سیاست | 
|---|---|---|
| `POST /upload/product|testimonial` | content | Magic signature، ذخیره خصوصی، انتشار اولیه False، ۱۰ MB عکس/۵۰ MB سایر |
| `POST /upload/campaign` | marketing | قفل Draft قبل از آپلود؛ Approved و Sending تغییر نمی‌کنند |
| `GET /media/preview/{kind}/{id}` | content/marketing | احراز هویت، Role، Content-Security-Policy sandbox، No-Store |
| `PATCH/DELETE /media/{id}` | content | تغییر Caption موجب لغو انتشار؛ حذف فقط در حالت unpublished |
| `PATCH/DELETE /testimonials/{id}` | content | تغییر متن موجب لغو تأیید؛ حذف فقط تأییدنشده |
| `DELETE /campaigns/{id}/media/{id}` | marketing | فقط Draft، بدون تغییر کمپین تأییدشده |
| `POST /broadcast/prepare/{id}` | marketing | تأیید صریح؛ فقط چت خصوصی بله و API معمولی؛ نه ارسال Broadcast |
| `POST /orders/{id}/review` | sales | تصمیم Manual فقط `approved_unpaid` یا `cancelled`، Audit؛ هرگز Paid |
| `POST /wallets/adjust` | finance | کلید UUID برای Idempotency، سقف تنظیم‌شده، Ledger، بدون کیف پول بله |
| `POST /refunds/{id}/resolve` | finance | سرویس اصلی Python، مدرک مستقل؛ Stars فقط با Flag و API رسمی |
| `GET/POST/PATCH /staff` | superadmin | Argon2، حفاظت از آخرین مدیر، ابطال تمام Sessionهای قدیمی |
| `GET/PATCH /referral-policy` | superadmin | درصد ۰ تا ۳۰ و محدودیت اعداد ریالی؛ بدون تغییر سوابق |

**جریان Upload:** مرورگر فارسی RTL → `/api/admin/upload` در Next.js
(بررسی Origin دقیق HTTPS، Session، محدودیت ۵۰٫۱ MB) → HMAC-SHA256 روی
بایت‌های اصلی فرم → FastAPI، بررسی Staff/Role/حجم/امضای فایل →
`save_media` و PostgreSQL → Preview اختصاصی بدون افشای Storage Key.
این مسیر عمدی از Server Action استفاده نمی‌کند تا با سقف Body پیش‌فرض
آن برخورد نکند.

**مراحل باقی‌ماندهٔ پذیرش:**

1. ساخت Lockfile معتبر، `npm ci`، `typecheck`، `lint` و `next build`؛
   بررسی نسخهٔ واقعی Next.js و سازگاری Runtime.
2. اجرای `pytest -q tests/test_next_admin_bridge.py tests/test_next_admin_operations_offline.py`
   در محیط ایزوله و تست Request اصلی Multipart/Starlette.
3. تست PostgreSQL و Redis واقعی: RBAC، نشت فایل، کپی Body، انقضای HMAC،
   Session Revocation، Audit و تراکنش‌های هم‌زمان.
4. تست مرورگر RTL، Dark Mode، موبایل و آپلود واقعی با فایل‌های نمونهٔ
   بی‌خطر در حدود سقف‌ها؛ بررسی سقف Proxy و مصرف RAM.
5. بررسی مستقل Refundهای واقعی، Provider Pending، قفل مالی و Broadcast
   صرفاً در Sandbox/محیط آزمایشی؛ سپس تصمیم صریح برای Deploy.

تا آن زمان، این شاخه **فقط توسعهٔ سورس است** و هیچ استقرار، انتشار یا
ارسال واقعی نباید انجام شود.
