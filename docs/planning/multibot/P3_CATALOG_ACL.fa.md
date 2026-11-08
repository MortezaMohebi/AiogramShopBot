# P3 — Bot Catalog ACL و دسترسی Many2many محصولات

**Branch:** `feat/multibot-catalog-acl-20261103`  
**Parent:** `feat/multibot-management-20261103` (PR #7)  
**Migration:** `20261103r001` بعد از `20261103q001`  
**وضعیت:** Source پیاده‌سازی شده؛ تست عملیاتی Codespace، PostgreSQL و Next.js هنوز تأیید نشده است.

## هدف

هر بات تلگرام یا بله می‌تواند فقط محصولات و دسته‌بندی‌های مجاز خود را ببیند و بخرد. محصولات، قیمت و موجودی در `shop_products` همچنان مشترک باقی می‌مانند؛ جدول‌های سیاست به‌صورت Many2many و بدون تغییر جداول اصلی افزوده شده‌اند.

- `shop_bot_product_rules`: کلید مرکب `(bot_id, product_id)`، مقدار `allow|deny`.
- `shop_bot_category_rules`: کلید مرکب `(bot_id, category_id)`، مقدار `allow|deny`.
- `shop_bot_catalog_audit`: تاریخچهٔ غیرقابل ویرایش قبلی/جدید هر قانون، مدیر و زمان.
- `inherit` یک مقدار ذخیره‌شده نیست؛ حذف رکورد صریح است و اثر آن طبق سیاست دسته‌بندی و پیش‌فرض بات تعیین می‌شود.

## ترتیب تصمیم‌گیری — منبع حقیقت مشترک

۱. محصول منتشرنشده در هیچ باتی نمایش داده نمی‌شود.

۲. Product Deny صریح، بدون توجه به دسته‌بندی، محصول را ممنوع می‌کند.

۳. Product Allow صریح از Category Deny اولویت بالاتری دارد.

۴. اگر قانون صریح محصول موجود نباشد، Category Deny یا Category Allow اعمال می‌شود.

۵. اگر هیچ قانونی موجود نباشد، Legacy Botها به دلیل سازگاری با فروش قبلی **Allow** هستند و بات‌های جدید Registry به‌صورت پیش‌فرض **Deny** هستند.

۶. باتی که Store فعال یا Runtime مجاز ندارد، هیچ دسترسی واقعی ندارد؛ حتی اگر در Preview مدیر قانون Allow داشته باشد. فروشگاه‌های تازه در Phase 4 کاتالوگ مستقل خواهند داشت و در P3 به کالای فروشگاه اصلی دسترسی نمی‌گیرند.

**توجه:** این ترتیب مخصوص `shop_products` است؛ فروشگاه قدیمی تلگرام در `Item` و Handlerهای قدیمی خود یک ساختار مجزا دارد. ادغام کامل آن و حذف مسیرهای قدیمی در P4 باید با Migration مستقل و بررسی سفارش‌های قبلی انجام شود.

## پوشش واقعی Backend

| مسیر | کنترل |
|---|---|
| کاتالوگ و صفحه‌بندی محصولات | SQL WHERE بر اساس همان Predicate مشترک ACL، بدون دریافت محصول ممنوع |
| صفحه‌بندی دسته‌بندی‌ها | فقط Category منتشرشده‌ای که حداقل یک محصول مجاز دارد |
| `shop:item:{id}` | بررسی مجدد ACL روی Callback قدیمی و مستقیم |
| `shop:files:{id}` و `shop:reviews:{id}` | بررسی ACL قبل از بارگذاری و ارسال هر رسانه/رضایت |
| `shop:add/inc` | بررسی ACL قبل از ایجاد/افزایش Cart Line |
| Quote و صفحهٔ سبد | بررسی ACL همهٔ اقلام؛ نام و قیمت کالای محروم‌شده در پیام رفع مشکل افشا نمی‌شود |
| Checkout Preview و Place Order | بررسی دوباره، به همراه قفل ردیف Bot در لحظهٔ ثبت سفارش |
| ایجاد فاکتور جدید | بررسی ACL پیش از ساخت Payment Attempt، همراه با Bot Lock |
| Telegram/Bale Pre-checkout | بررسی ACL دوباره؛ دریافت رسید پرداخت انجام‌شده همچنان قابل Reconcile است |
| Store Credit | بررسی ACL قبل از کسر اعتبار و ثبت سفارش تسویه‌شده |

**رویدادهای مالی قبلی:** تغییر ACL هرگز نباید یک رسید پرداخت قطعی قبلی را حذف کند. `settle` و `refund` عمداً با قوانین جدید فروش از بین نمی‌روند. صدور *فاکتور جدید* از موجودی سفارش قدیمی پس از محروم‌شدن محصول مسدود می‌شود.

## صفحات پنل

- `/bots/{id}`: بخش محصولات/دسته‌بندی‌ها، جست‌وجو، صفحه‌بندی، انتخاب چند ردیف و اعمال Allow/Deny/Inherit به‌صورت گروهی؛ هر عملیات دارای Version Lock و Audit.
- `/products/{id}/edit`: بخش Many2many انتخاب چندباتی با فیلتر، صفحه‌بندی و همان سه Effect. فقط `superadmin` می‌تواند ACL را تغییر دهد. کاربران `content` همچنان می‌توانند سایر فیلدهای محصول را طبق Permission قبلی ویرایش کنند.
- محصول تازه ابتدا در کاتالوگ مرکزی ایجاد می‌شود؛ بعد از صدور Product ID، فرم ویرایش امکان تعیین ACL را فعال می‌کند.
- برای Storeهای تازه و غیرآماده امکان صدور مجوز واقعی برای کالاهای Store اصلی وجود ندارد.

## امنیت و API

| Method | Route | Scope |
|---|---|---|
| GET | `/internal/admin/v1/bot-catalog/bots/{bot_id}` | بات، نوع Product/Category، جست‌وجو و صفحه |
| POST | `/internal/admin/v1/bot-catalog/bots/{bot_id}/rules` | تغییر ۱ تا ۱۰۰ قانون به شکل اتمیک |
| GET | `/internal/admin/v1/bot-catalog/products/{product_id}` | انتخاب Many2many بات‌ها از محصول |
| POST | `/internal/admin/v1/bot-catalog/products/{product_id}/rules` | تغییر ۱ تا ۱۰۰ رابطهٔ نسخه‌دار |
| GET | `/internal/admin/v1/bot-catalog/bots/{bot_id}/audit` | تاریخچهٔ محدود تغییرات |

همهٔ Mutationها به `bots.configure`، HMAC Bridge معتبر، Session فعال و Re-authentication اخیر نیاز دارند. ورودی UUID و شناسه‌های عددی اعتبارسنجی می‌شوند. فقط Botهای `DEFAULT_STORE_ID` می‌توانند با کاتالوگ مشترک فعلی ارتباط داشته باشند. Version Check از بازنویسی خاموش تنظیمات هم‌زمان جلوگیری می‌کند.

در P3 بات‌های جدید همچنان Draft و بدون Receiver هستند؛ دریافت Webhook/Polling چندباتی، جداسازی Basket/Wallet/Customer و اتصال Worker Pool به P4/P5 وابسته است. `BotContext` تنها پس از اعتبارسنجی Adapter قابل ارائه به CatalogFlow است و Callback عمومی اجازهٔ انتخاب `bot_id` ندارد.

## Migration بدون حذف دیتا

- فقط سه جدول ACL جدید و Indexهای آن‌ها ایجاد می‌شوند.
- هیچ ستون `shop_products`، `shop_categories`، `shop_orders`، `shop_carts`، `shop_wallet_entries`، Inbound Update یا دادهٔ قبلی Update/Delete نمی‌شود.
- در ابتدای نصب هیچ Rule‌ای ثبت نمی‌شود؛ بنابراین دو بات Legacy محصولات منتشرشدهٔ خود را از دست نمی‌دهند.
- Downgrade از پاک‌کردن تاریخچهٔ مجوز جلوگیری می‌کند.
- Codespaces Bootstrap فقط جداول مجاز جدید را به‌صورت افزایشی می‌سازد؛ Reset حجم‌های موجود ممنوع است.

## آزمون پذیرش و ماتریس خطر

- [x] ساختار مدل، Migration، سرویس SQL Policy، Backend API و صفحات Next.js در GitHub ثبت شدند.
- [x] تست‌های آفلاین Predicate، پیش‌فرض Legacy/New Bot، تعارض Product/Category، انقضا/تعویض قانون، Callbackهای قدیمی، Cart و Invoice نوشته شدند.
- [ ] اجرای واقعی `pytest -q tests/test_multibot_catalog_acl_offline.py`.
- [ ] اجرای `pytest -q tests/test_shop_channel_catalog.py tests/test_shared_cart.py tests/test_shared_payment_settlement.py` و تمام Regressionها.
- [ ] `python -m compileall` برای مدل‌ها، سرویس‌ها و Routerها.
- [ ] Migration `alembic upgrade head` روی Snapshot PostgreSQL با شمارش Before/After سفارش، مشتری، موجودی، Ledger و Media.
- [ ] اجرای دوبارهٔ Codespaces Bootstrap بدون Reset و بدون Rule تکراری.
- [ ] `npm --prefix dashboard-next run typecheck`، `lint` و `build`.
- [ ] Playwright Desktop/RTL/Mobile، مجوز Content در برابر Superadmin، فرم محصول و فرم بات و CSRF.
- [ ] دو بات Legacy با محصول مشترک و قوانین متفاوت؛ دسترسی با Callback کپی‌شده رد شود.
- [ ] تست هم‌زمان تغییر ACL و ثبت سفارش/صدور فاکتور با PostgreSQL Row Locks.
- [ ] آزمون پرداخت قدیمی/Refund بعد از Deny و حفظ حساب مالی بدون تغییر.
- [ ] آزمون انتشار Media و Asset URL برای جلوگیری از دسترسی خارج از Bot API. دسترسی مستقیم به فایل‌های از پیش منتشرشده نیازمند بررسی جداگانهٔ Cache/URL است.

**این تست‌ها در این گفت‌وگو اجرا نشده‌اند و هیچ مرحله‌ای هنوز به‌عنوان PASS عملیاتی یا آمادهٔ Production تأیید نشده است.** PR باید Draft بماند.
