# نقشهٔ اجرای Multi-Bot — ترتیب قطعی فازها

**Repository:** MortezaMohebi/AiogramShopBot  
**Foundation branch:** `feat/multibot-foundation-20261103`  
**Bot Management (P2):** `feat/multibot-management-20261103`  
**Bot Catalog ACL (P3):** `feat/multibot-catalog-acl-20261103`  
**Parent branch:** `feat/staff-security-invites-mfa-audit-20261103` (PR #5، هنوز Draft)  
**اصل معماری:** One Store → Many Bots؛ Shared Product Catalog با دسترسی اختصاصی هر بات؛ Many Bots → Many outbound Worker/Proxy Routes.

این برنامه از کار روی Runtime، Wallet یا Webhook پیش از وجود هویت مستقل بات جلوگیری می‌کند. تا قبولی تست‌های هر فاز، فاز بعدی نباید بر روی Production فعال شود.

## ترتیب و شرط عبور

| ترتیب | فاز | محدودهٔ دقیق | وابستگی | خروجی و شرط پذیرش |
|---|---|---|---|---|
| 1 | Foundation | `ShopStore`، `ShopBot`، Bot Credential Vault، `BotContext`، Backfill قدیمی و Alembic افزایشی | PR #5، Migration `20261103o001` | دو بات قبلی با شناسهٔ ثابت دیده شوند؛ هیچ Token در GET/Logs؛ بات جدید `draft` بماند؛ اطلاعات مالی تغییر نکند |
| 2 | Bot Management & Operations | پنل لیست/ساخت/تأیید `getMe`، روشن/خاموش، Maintenance، توقف امن، RBAC و سلامت هر بات | Phase 1 | آزمون حداقل ۲ تلگرام و ۲ بله؛ هر بات مستقل؛ هیچ بات Draft بدون تأیید شروع نشود |
| 3 | Bot Catalog Access | جدول قوانین دسترسی Many2many محصول/دسته‌بندی، وضعیت Deny/Allow، پیش‌فرض Deny برای بات جدید و فیلد Many2many در Product Editor | Phase 2 | لیست محصول، جست‌وجو، رسانه، Callback قدیمی، Cart و Checkout همگی یک قانون مشترک را اجرا کنند |
| 4 | Multi-Bot Runtime & Commerce | Webhook/Polling مستقل، Redis/FSM/Offset/Lease per-bot، `bot_id` در Identity/Cart/Order/Payment/Wallet/Referrals/Broadcast، Migration داده‌های سابق | Phases 1–3 | عدم تداخل User ID برابر، عدم اختلاط سبد و اعتبار، پرداخت‌ها و Refunded/Success قدیمی محفوظ؛ ۴ بات واقعی تست شوند |
| 5 | Relay/Worker Pool | Registry چند Worker، تخصیص `Bot ↔ Worker` با اولویت، Worker auth تفکیک‌شده و Secret rotation، ظرفیت، Rate Limit و failover فقط برای کار ایمن | Phase 4 | چند بات روی یک Worker و یک بات روی دو Worker تست شوند؛ timeout ارسال پیام باعث Retry کور نشود |
| 6 | Migration, E2E and Rollout | Dual-read/compatibility window، Cutover قابل بازگشت، تست شبکه و Load، تله‌متری، پاکسازی تدریجی legacy بعد از پذیرش | Phases 1–5 | تست Codespace/PostgreSQL/Playwright/Provider، مستندات Recovery و Merge تدریجی با تأیید انسانی |

## وضعیت فعلی فازها — ۳ نوامبر ۲۰۲۶

| فاز | پیاده‌سازی سورس | پذیرش واقعی |
|---|---|---|
| P1 Foundation | در PR #6 ثبت شده | PostgreSQL / Codespace / Pytest تأیید نشده |
| P2 Bot Management & Operations | مدل، API، RTL UI، Legacy Gates، Credential Verification و تست‌های آفلاین در Branch مستقل ثبت شده | Docker/PostgreSQL/Playwright/Provider هنوز تأیید نشده |
| P3 Bot Catalog Access | سه جدول ACL، Predicate مشترک، کنترل Catalog/Callback/Cart/Checkout، پنل Many2many بات و محصول و تست‌های آفلاین در Branch مستقل ثبت شده | Docker/PostgreSQL/Playwright/Provider هنوز تأیید نشده |
| P4 Multi-Bot Runtime & Commerce | شروع نشده | شروع نشده |
| P5 Shared Relay Worker Pool | شروع نشده | شروع نشده |
| P6 Migration & Final Acceptance | شروع نشده | شروع نشده |

جزئیات فاز سوم و شرط پذیرش آن در
[`P3_CATALOG_ACL.fa.md`](./P3_CATALOG_ACL.fa.md) ثبت شده‌اند.

جزئیات دقیق و آزمون‌های موردنیاز فاز دوم در
[`P2_BOT_MANAGEMENT.fa.md`](./P2_BOT_MANAGEMENT.fa.md) ثبت شده‌اند.

**مرز P3:** تنظیم Rule برای بات جدید به معنی فعال‌شدن آن نیست؛
فروشگاه‌های تازه نیز تا ایجاد Tenant Catalog مستقل در P4 نمی‌توانند
محصول فروشگاه اصلی را نمایش دهند. Product/Category ACL فقط در کاتالوگ
`shop_products` جاری اعمال شده و مجموعهٔ Legacy `Item` نیازمند
برنامهٔ Migration مستقل است.

**مرز عمدی:** روشن/خاموش‌کردن در P2 فقط برای دو Bot Legacy واقعاً به مسیر فروش/پیام‌های عادی اعمال می‌شود. Botهای جدید همچنان Draft و بدون Webhook/Dispatcher/Payment هستند تا P4 تکمیل شود. هیچ حالت آماده‌بودن زنده‌ای برای آن‌ها ادعا نمی‌شود.

## نکات ثابت در تمام فازها

1. **Store و Bot مستقل‌اند.** کالا و موجودی فعلاً مشترک‌اند؛ اما دسترسی فروش و نمایش از طریق `bot_id` کنترل می‌شود.
2. **شناسهٔ کاربر سراسری نیست.** کلید حساب مشتری، Cart و Consent باید در نسخهٔ جدید `(bot_id, platform_user_id)` باشد. برابری User ID در دو بات به معنی یک شخص یا یک کیف پول نیست.
3. **Secret یک دادهٔ Backend است.** Token، Relay Key و Proxy Password در URL، وضعیت JSON، Commit، Log، Export و Audit قرار نمی‌گیرند.
4. **وقفهٔ امن پرداخت:** تعطیلی بات جلوی فروش جدید را می‌گیرد؛ اما رسیدهای قدیمی، Refund و Reconciliation نباید رها شوند.
5. **Receiver یک مالک قابل اثبات دارد.** برای هر بات Webhook/Polling، Offset، Inbound Receipt و Lock مستقل است. تغییر `drop_pending_updates=true` ممنوع است مگر با طراحی مجزا و تأیید.
6. **اشتراک Cloudflare Worker به معنی اشتراک Secret نیست.** در Phase 5، Worker می‌تواند چند Credential مستقل را شناسایی و Rate Limit کند؛ API upstream همیشه دامنهٔ ثابت Telegram است.
7. **Failover فقط برای درخواست‌های امن.** Timeout از API ارسال پیام نتیجهٔ نامشخص است، نه مجوز ارسال مجدد.
8. **Migration افزایشی است.** ساخت جدول جدید، Backfill نسخه‌دار و بعد از تطبیق استفادهٔ جدید؛ حذف ستون/جدول قدیمی در فاز اول و دوم ممنوع است.
9. **فعال‌سازی با مجوز مشخص.** کد Foundation مجوز عملیاتی فعال‌سازی Bot جدید یا انتشار فروشگاه جدید را ندارد.

## Phase 1 — چه چیزی ثبت شده است؟

- [x] `shop_stores` و `shop_bots` با UUID ثابت برای دو بات Legacy و یک Store پیش‌فرض.
- [x] `shop_bot_credentials` با نسخهٔ رمزنگاری‌شده یا Environment Reference و حالت Staged/Active/Revoked.
- [x] `shop_bot_registry_events` برای Audit بدون Secret.
- [x] سرویس `shop_bot_registry` برای Store غیرفعال و Bot Draft؛ بدون انجام عملیات خارجی.
- [x] سرویس `shop_bot_secrets` با Fernet مستقل/مشتق‌شده و Binding رمز به Bot ID/Provider.
- [x] `BotContext` immutable برای محدودهٔ Store + Bot + Platform و مالکیت جداگانهٔ مشتری.
- [x] Alembic `20261103p001_multibot_foundation.py` و Seed افزایشی Codespaces.
- [x] API داخلی HMAC/Session برای لیست، ساخت Draft و Token Staging؛ RBAC + Reauthentication.
- [x] تست‌های آفلاین جدید ثبت شده‌اند.
- [ ] اجرای واقعی Test/Lint و اطمینان از PASS.
- [ ] اجرای `alembic upgrade head` روی کپی PostgreSQL دارای سفارش/موجودی قبل و بعد از ارتقا.
- [ ] تأیید `scripts.security_bootstrap` بدون Reset، و تست تکرار Bootstrap.
- [ ] تأیید مسیر API روی دو مرورگر و ثبت Audit، بدون افشای Token.
- [ ] اطمینان از اینکه bot.py/run.py و سرویس‌های فعلی بدون تغییر عملیاتی همچنان کار می‌کنند.

**اتمام سورس به معنی پذیرش Production نیست.** تا زمان پاس‌شدن همهٔ موارد QA، PR باید Draft بماند.

## سیاست Branch و PR

- PR #5 پایهٔ مرحلهٔ امنیت و کنترل‌های فعلی است؛ هیچ تغییر Foundation مستقیماً در آن Branch نوشته نشود.
- Phase 1 یک PR مستقل و **stacked** روی Branch PR #5 دارد.
- Phase 2 روی `feat/multibot-management-20261103` از Foundation اجرا شده و PR مستقل Draft دارد؛ اجرای واقعی تست‌ها هنوز باقی است.
- بعد از Merge شدن PR #5، Base این PR باید به Branch پذیرفته‌شده تغییر کند، و کل تست‌ها مجدداً اجرا شوند.
- برای هر فاز حداقل: Migration/Model/API Test → Authorization Negative Test → Legacy Regression → Codespace Docker/PostgreSQL → Next.js/Playwright → Provider Simulation → Review/Approval.

## مسیر بازگشت

Foundation فعلی هیچ دادهٔ قدیمی را انتقال یا حذف نمی‌دهد. اگر فعال‌سازی آن مشکل ایجاد کرد، به کد قبلی برگردید و داده‌های افزایشی Registry را دست‌نخورده نگه دارید. Downgrade این Migration به‌طور عمدی حذف جداول را انجام نمی‌دهد و بدون مسیر محافظت‌شدهٔ حفظ داده متوقف می‌شود.
