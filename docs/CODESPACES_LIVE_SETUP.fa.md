# راه‌اندازی Registry در Codespaces

ورودی برنامه `scripts.secure_app:app` است. Dashboard، PostgreSQL، Redis و یک Receiver Pool مشترک اجرا می‌شوند. هر ربات باید از صفحهٔ «مدیریت ربات‌ها» ثبت و تأیید شود؛ نصب تازه هیچ ربات یا Credential پیش‌فرضی ایجاد نمی‌کند.

```bash
bash scripts/setup_codespace.sh init
bash scripts/setup_codespace.sh start
bash scripts/setup_codespace.sh status
bash scripts/setup_codespace.sh auth-smoke
```

`init` تنظیمات خصوصی محیط و کلیدهای مستقل ایجاد می‌کند. Token پیام‌رسان در Setup یا Codespaces Secrets تعریف نمی‌شود. حساب مدیر تازه باید ورود عادی و ثبت MFA را کامل کند؛ اجرای دوبارهٔ Setup رمز یا MFA حساب موجود را عوض نمی‌کند.

در بخش **Ports**، پورت Dashboard را باز کنید. Dashboard و API داخلی Private می‌مانند. پورت Gateway فقط برای دریافت پیام از Provider لازم است؛ Public کردن آن و ثبت Webhook دو اقدام جدا هستند. راه‌اندازی محیط به‌تنهایی هیچ Webhook یا Workflow مشتری را فعال نمی‌کند.

## ثبت ربات

۱. در Dashboard، Store فعال را انتخاب کنید و به «مدیریت ربات‌ها» بروید.
۲. یک Draft برای Telegram یا Bale ایجاد کنید.
۳. پس از احراز هویت مجدد، Token همان ربات را Stage و هویت Provider را Verify کنید.
۴. سیاست محصولات، قابلیت‌های خرید و Receiver همان ربات را بررسی کنید.
۵. فعال‌سازی Receiver و انتشار Workflow را فقط با تأیید هدف و نسخهٔ مشخص انجام دهید.

Tokenها رمزگذاری می‌شوند و در پاسخ API یا گزارش‌ها نمایش داده نمی‌شوند. Receiver فقط مسیر `POST /webhooks/v2/{binding_id}/{route_secret}` را استفاده می‌کند؛ Token بخشی از URL نیست. مسیرهای قدیمی Telegram/Bale و پنل SQLAdmin وجود ندارند.

## Schema تازه و پاک‌سازی

Bootstrap فقط در دیتابیس اختصاصی و محافظت‌شدهٔ Codespaces مجاز است. Schema از مدل‌های فعلی ساخته می‌شود؛ Migrationهای تاریخی SQLite روی دیتابیس تازه اجرا نمی‌شوند. اجرای مجدد باید Store، UoM و دسترسی مدیر را حفظ کند و ربات نسازد.

برای محیط قدیمی، ابتدا Backup بگیرید و Dry Run را در Container همان محیط اجرا کنید:

```bash
python -m scripts.legacy_schema_cleanup
python -m scripts.legacy_schema_cleanup --apply
```

Apply فقط با Guardهای دیتابیس اختصاصی انجام می‌شود. عملیات از فهرست ثابت جدول‌های بازنشسته استفاده می‌کند و `CASCADE` ندارد. وجود Foreign Key ناشناخته، تنظیمات متعارض یا Link مشتری تبدیل‌نشده باعث توقف کامل Transaction می‌شود. اطلاعات فعلی حساب مدیریت، MFA، Store، سفارش‌ها و رسیدها حذف نمی‌شوند.

برای توقف و مشاهدهٔ وضعیت:

```bash
bash scripts/setup_codespace.sh status
bash scripts/setup_codespace.sh logs
bash scripts/setup_codespace.sh stop
```

`reset --yes` مخصوص محیط آزمایشی دورریختنی است و جایگزین Cleanup یا Migration دیتابیس دارای اطلاعات نیست. جزئیات قرارداد در [Registry-only retirement](REGISTRY_ONLY_RETIREMENT.md) ثبت شده است.
