# ADR — Foundation چندباتی، قراردادها و سازگاری با نسخهٔ قبلی

**Status:** Implemented in source, pending integration acceptance  
**Parent:** \`feat/staff-security-invites-mfa-audit-20261103\`  
**Migration:** \`20261103p001\` بعد از \`20261103o001\`

## ۱. Store و Bot

مدل \`ShopStore\` هر فروشگاه را با UUID و Slug یکتا مشخص می‌کند. یک Store پیش‌فرض با شناسهٔ قطعی برای کاتالوگ موجود ثبت می‌شود. Storeهای جدید تا آماده‌شدن Catalog Multi-Tenant در حالت \`paused\` هستند و نباید دسترسی به کاتالوگ Store اول داشته باشند.

\`ShopBot\` با UUID، \`store_id\`، \`platform\` (فقط \`telegram\` یا \`bale\`)، Slug، نام، وضعیت، نسخه و هویت تأییدشدهٔ Provider ذخیره می‌شود. ترکیب \`(store_id, slug)\` یکتا است؛ ترکیب \`(platform, provider_bot_id)\` نیز برای شناسهٔ غیر NULL منحصربه‌فرد است. Token و رمز Proxy در این جدول **وجود ندارند**.

دو بات فعلی با شناسه‌های UUIDv5 پایدار در Store پیش‌فرض ثبت می‌شوند. حالت آن‌ها \`legacy\` و \`runtime_owner=legacy\` است. این وضعیت ادعای فعال‌سازی Runtime جدید نیست، بلکه نگاشت بدون تخریب برای Migration آتی است.

## ۲. Secret Management

\`ShopBotCredential\` دارای نسخهٔ افزایشی، حالت \`staged|active|revoked\` و Source مشخص است:

- \`environment\`: فقط برای دو بات Legacy با Reference ثابت به \`TOKEN\` یا \`BALE_BOT_TOKEN\`. هیچ کپی plaintext به DB انجام نمی‌شود.
- \`encrypted\`: Credential جدید با Fernet و مستند JSON شامل \`schema\`، \`bot_id\`، \`platform\` و \`token\` رمز می‌شود. هنگام Decrypt، هر دو شناسه با رکورد اصلی تطبیق داده می‌شوند.
- کلید ترجیحی \`SHOP_BOT_SECRET_KEY\` یک Fernet Key تصادفی ۳۲ بایتی Base64 URL-safe است. در صورت نبود آن، از \`SHOP_SECURITY_ENCRYPTION_KEY\` با HMAC-SHA256 و \`aiogramshopbot:bot-token-storage:v1\` کلید مخصوص Token مشتق می‌شود. این کلیدها نباید ناگهانی Rotate یا حذف شوند.
- \`POST /bot-registry/{id}/credentials/stage\` Token خام را فقط از مرز authenticated Next.js/FastAPI می‌پذیرد. نتیجه فقط نسخه و وضعیت را بازمی‌گرداند؛ Token یا Ciphertext هرگز بازگشت داده نمی‌شود.
- نسخهٔ Staged تنها برای بات \`draft\` مجاز است. هیچ مسیر Public/REST برای Promote یا Activate Secret در فاز Foundation وجود ندارد.
- \`resolve_active_token\` فقط در سرویس‌های داخلی و پس از تأیید هویت Receiver مجاز است؛ ورودی خام کاربر معیار تعیین بات نیست.

## ۳. BotContext

\`services/shop_bot_context.py\` یک Dataclass immutable با \`bot_id, store_id, platform, provider_bot_id, status, runtime_owner, credential_version, registry_version\` ایجاد می‌کند و هیچ Token ندارد.

این Context تنها بعد از Authenticated Webhook Binding یا Job Polling متعلق به بات ایجاد می‌شود. \`owner_key(user_id) -> (bot_id, user_id)\` کلید آیندهٔ مالکیت را تعریف می‌کند. **هنوز هیچ Handler یا جدول قدیمی را مجبور به استفاده از آن نکرده‌ایم.** مهاجرت واقعی Customer/Cart/Order/Wallet مربوط به Phase 4 است.

## ۴. Backfill بدون حذف دیتا

Migration چهار جدول جدید اضافه می‌کند و از \`shop_bot_profiles\` مشخصات غیرمحرمانهٔ هر پیام‌رسان را فقط **می‌خواند**. دادهٔ \`shop_settings.brand_name\` فقط برای نام Store پیش‌فرض استفاده می‌شود. داده‌های جاری شامل \`shop_orders\`، \`shop_carts\`، \`shop_identities\`، \`shop_wallet_entries\`، Receiver Mode و Telegram Transport با \`UPDATE/DELETE/DROP\` تغییر نمی‌کنند.

برای Codespaces، \`scripts.security_bootstrap\` فهرست جداول جدید را به Create-All افزایشی اضافه کرده و با \`ON CONFLICT DO NOTHING\` فقط در صورت نبودن رکوردهای Legacy، آن‌ها را ثبت می‌کند؛ داده‌های موجود بازنویسی نمی‌شوند. اعمال کد روی Production نیازمند Backup و \`alembic upgrade head\` روی یک کپی آزمایشی است.

Downgrade آگاهانه fail-closed است تا حذف تصادفی Registry یا تاریخچهٔ Secret انجام نشود.

## ۵. APIهای Foundation

| Method | Route | عملیات | Permission |
|---|---|---|---|
| GET | \`/internal/admin/v1/stores\` | لیست Storeها | \`bots.read\` |
| POST | \`/internal/admin/v1/stores\` | ساخت Store جدید \`paused\` | \`bots.configure\` + Reauth |
| GET | \`/internal/admin/v1/bot-registry\` | مشاهده بات‌ها و وضعیت Secret بدون نمایش Secret | \`bots.read\` |
| POST | \`/internal/admin/v1/bot-registry\` | ساخت Bot Draft | \`bots.configure\` + Reauth |
| POST | \`/internal/admin/v1/bot-registry/{id}/credentials/stage\` | رمزگذاری و Stage Token | \`bots.configure\` + Reauth |
| POST | \`/internal/admin/v1/bot-registry/{id}/credentials/revoke\` | لغو Credential استفاده‌نشده | \`bots.configure\` + Reauth |

این‌ها APIهای داخلی Backend هستند؛ در Phase 2 UI مدیریت چندباتی و تأیید واقعی \`getMe\` اضافه می‌شود. هیچ API جدیدی برای شروع Receiver، ارسال Broadcast، اجرای پرداخت یا اتصال Worker در این مرحله تعریف نشده است.

## ۶. Acceptance و موارد باقی‌مانده

1. تست واحد: \`pytest -q tests/test_multibot_foundation_offline.py\`.
2. Regression: \`pytest -q\`، ترجیحاً با PostgreSQL آزمایشی و حفظ داده‌های قبلی.
3. Migration: عکس قبل/بعد از تعداد سفارش، سبد، تراکنش، هویت مشتری و تنظیمات دو بات؛ مقادیر برابر بمانند.
4. Bootstrap: اجرای دوباره بدون Duplication و بدون پاک‌شدن Secret.
5. امنیت: درخواست بدون امضا، Session منقضی، کاربر فاقد Permission، POST بدون Reauth و Attempt برای Promote/Read Token رد شوند.
6. Typecheck/Lint/Build پنل؛ این فاز UI جدید ندارد ولی یکپارچگی کد باید تأیید شود.
7. تأیید محیط زنده Telegram/Bale فقط با بات‌های آزمایشی، نه Production.

**در زمان ثبت این فایل‌ها هنوز اجرای واقعی تست، Migration و Docker در Codespace تأیید نشده است.**
