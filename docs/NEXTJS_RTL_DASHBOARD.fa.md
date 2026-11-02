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
- به‌جای انتقال ناگهانی، SQLAdmin قبلی روی مسیر اصلی باقی می‌ماند تا
  رسانه‌های حجیم، Refund و تنظیمات حساس بدون مسیر ناامن مدیریت شوند.

### جریان متنی قابل تبدیل به دیاگرام

```text
Browser (HTTPS, Persian RTL)
  |
  | HttpOnly + Secure + SameSite=Strict Staff Cookie
  v
Next.js (one shared dashboard, App Router)
  | Server Components + Server Actions
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
| Orders | مشاهده بدون جعل وضعیت Paid | sales/finance/superadmin |
| Customers | مشاهده هویت و Opt-in جدا برای هر پیام‌رسان | sales/superadmin |
| Shipping | CRUD هزینه ارسال با عدد صحیح ریال | sales/superadmin |
| Coupons | CRUD درصد/مبلغ، اعتبار، سقف استفاده | marketing/superadmin |
| Campaigns | ایجاد Draft، Approve، Start با سقف هزینه، Pause/Resume/Cancel | marketing/superadmin |
| Campaign Details | بررسی گیرنده Unknown با مدرک، بدون بازپخش | marketing/superadmin |
| Reports | درآمد ریالی، Credit و XTR جدا، لیست پرفروش‌ها | تمام کارکنان |
| Settings | نام فروشگاه، پیام خوش‌آمد، FAQ، پشتیبانی | superadmin |
| Media | نمایش metadata امن، انتقال Upload به مرحله بعد | content/superadmin |
| Reviews | فهرست رضایت مشتری، وضعیت تأیید | content/superadmin |
| Finance | فهرست حساب اعتباری و پرونده Refund، فقط خواندن | finance/superadmin |

**محدودیت‌های واقعی:** پشتیبانی از Upload مستقیم ۵۰ MB و تأیید انتشار
محتوا، اجرای Refund و تعدیل اعتبار، ساخت کاربران مدیریتی و مهاجرت داده
تاریخی Telegram هنوز از مسیر SQLAdmin/CLI محافظت‌شده انجام می‌شود.
این‌ها در رابط Next.js فعلاً Read-only یا دارای مسیر موقت SQLAdmin هستند.
تا زمان انتقال و آزمون کامل، SQLAdmin حذف نمی‌شود.

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
  استفاده می‌کند. API عمومی Next محدود به Login/Logout است؛
  State-changing server actions در Next.js و RBAC روی Backend کنترل می‌شوند.
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
              media, reviews, finance
    api/auth/login, api/auth/logout
  components/
    ui/               # shadcn-compatible primitives
    blocks/           # RTL layout, KPI, channel report and table blocks
  lib/
    bridge.ts         # HMAC API client; server-only
    session.ts        # HttpOnly cookie verifier
    types.ts, utils.ts, navigation.ts
  package.json, components.json, Dockerfile, .env.example
dashboard/next_api.py # Internal signed FastAPI JSON bridge
tests/test_next_admin_bridge.py
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
- [ ] ادامه تدریجی مهاجرت Media Upload، Referral/Wallet و مالی
      تا قبل از خاموش‌کردن SQLAdmin.
- [ ] عدم اجرای Broadcast/پرداخت واقعی در این مرحله.

**این برنچ یک مرحله توسعه است؛ آماده Merge نهایی، جایگزینی کامل SQLAdmin
یا پذیرش پرداخت واقعی نیست.**
