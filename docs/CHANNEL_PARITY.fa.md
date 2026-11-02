# ماتریس موازی Telegram / Bale (اسنپ‌شات مستندات ۱۴۰۵/۲۰۲۶)

این سند با استفاده از آرشیو رسمی ارائه‌شده `official_bot_docs_2026-11-02_complete(2).zip` تدوین شد.
SHA-256 فایل: `b02260dabc97e272496d5ce2d65314b0a6eabdbe1b2139cf7c81fef0200af405`.
لینک‌های مرجع: [Telegram Bot API](https://core.telegram.org/bots/api) و [Bale Bot API](https://docs.bale.ai/).

## قاعده اجرایی

هیچ قابلیت کانالی را صرفاً برای Telegram نهایی نمی‌کنیم. هر قابلیت در یک Vertical Slice شامل
`Core -> Telegram -> Bale -> Tests` توسعه می‌یابد. کدهای اختصاصی پلتفرم در `channels/`
محصور می‌مانند؛ `CatalogFlow` فقط `InboundEvent` و `BotReply` را می‌شناسد.

| رفتار | Telegram | Bale | وضعیت شاخه |
|---|---|---|---|
| متن UTF-8 و Inline Keyboard | Aiogram `send_message` | `sendMessage` HTTP JSON | کدنویسی‌شده؛ تست زنده باقی است |
| دریافت پیام | Webhook موجود Aiogram | Webhook مستقل `/webhooks/bale/{secret}` | کدنویسی‌شده؛ تست زنده باقی است |
| تشخیص callback | Aiogram Router | `callback_query.data` | کدنویسی‌شده؛ تست زنده باقی است |
| پاسخ callback | `answerCallbackQuery` | همان متد؛ شناسه‌های شروع‌شونده با ۱ در کلاینت قدیمی پشتیبانی ندارند | کدنویسی‌شده؛ تست زنده باقی است |
| فهرست کالا و صفحه‌بندی | `CatalogFlow` مشترک | `CatalogFlow` مشترک | کدنویسی‌شده؛ تست DB لازم است |
| مشخصات و قیمت محصول | رکورد `shop_products` | رکورد یکسان | کدنویسی‌شده؛ تست DB لازم است |
| رضایت مشتری | متن تأییدشده از DB | همان متن | کدنویسی‌شده؛ رسانه هنوز آماده نیست |
| ارسال و دریافت فایل | `file_id` مخصوص Bot / Upload | `file_id` مخصوص بازو / multipart | هنوز پیاده‌سازی نشده |
| خرید، موجودی و پرداخت | Legacy Telegram | نیازمند Core مشترک | هنوز در کانال مشترک آماده نیست |
| روش پرداخت دیجیتال | محدودیت‌های رسمی Telegram Stars | کیف پول بله و ریال | هنوز پیاده‌سازی نشده |

## اختلاف‌های مستندات که نباید پنهان شوند

- درخواست عادی بله: `https://tapi.bale.ai/bot<TOKEN>/<METHOD>`؛ API کسب‌وکاری
  `/business/bot` متفاوت و ممکن است هزینه داشته باشد؛ این پروژه از API **عادی** استفاده می‌کند.
- بله، `sendMessage` را با Markdown نمایش می‌دهد، درحالی‌که Aiogram upstream به‌طور پیش‌فرض HTML دارد.
  Adapter تلگرام در مسیر کاتالوگ `parse_mode=None` دارد. برای بله باید علامت‌گذاری متن
  و کاراکترهای رزروشده با تست میدانی کنترل شوند.
- `callback_data` بله حداکثر **۶۴ بایت** است؛ ما همین سقف را برای هر دو اعمال می‌کنیم.
- مستندات بله برای Webhook تنها `url` را اعلام می‌کنند، و پورت‌های ۴۴۳ و ۸۸ را پشتیبانی‌شده می‌دانند.
  در Snapshot، هدر `secret_token` مشابه تلگرام مستند نیست. بنابراین مسیر Webhook
  با Secret تصادفی حداقل ۳۲ کاراکتری حفاظت شده و **ثبت URL خام در Reverse Proxy باید خاموش/Redact شود**.
- بله آپدیت‌ها را حداکثر ۲۴ ساعت (۲۰۰۰ پیام آخر) نگه می‌دارد؛ Ack در Webhook فقط به
  معنای دریافت است، نه اثبات اجرای دقیقاً یک‌بار. پیش از تولید، Receipt/Idempotency لازم است.
- `file_id` بین ربات‌ها قابل اشتراک نیست و حتی برای دو ربات روی یک پلتفرم باید جدا ذخیره شود.
  رسانه اصلی باید از File Storage مستقل خوانده شود.
- هر دو پلتفرم `getUpdates` و Webhook را دارند، اما نباید روی یک ربات هم‌زمان فعال باشند.

## تنظیمات Bale در محیط عملیاتی

در `.env` مقدارهای زیر را **بدون Commit** تعریف کنید:

```env
BALE_BOT_TOKEN=<BALE_BOTFATHER_TOKEN>
BALE_WEBHOOK_SECRET=<RANDOM_SECRET_MIN_32_CHARACTERS>
SHOP_CURRENCY_LABEL=ریال
MULTIBOT=false
```

سپس آدرس `https://<your-domain>/webhooks/bale/<RANDOM_SECRET_MIN_32_CHARACTERS>`
را با متد `setWebhook` بله روی همان بازو ثبت کنید. برای Telegram همچنان
`TOKEN` و `WEBHOOK_SECRET_TOKEN` و مسیر فعلی محفوظ هستند. تنظیم Webhook بله فعلاً
**دستی** است و تا تأیید هویت/SSL/پیکربندی، نباید Bot واقعی را منتقل کرد.

## موارد باقی‌مانده تا پذیرش

1. آزمون مرورگر RTL و اجرای Migration روی PostgreSQL آزمایشی.
2. تست API واقعی `getMe`، `sendMessage`، `answerCallbackQuery` و Webhook در هر دو بستر
   با توکن‌های آزمایشی و بدون اجرای پرداخت.
3. فایل‌های اصلی، Upload امن و ارسال Photo/Video/Document در هر دو Adapter.
4. مدل یکپارچه هویت `(platform, platform_user_id)` و سفارش مشترک.
5. Deduplication آپدیت‌های Webhook و Idempotent Send و انقضای وضعیت‌ها.
6. یکسان‌سازی نهایی منوی ثابت با حذف مسیر قدیمی کاتالوگ پس از Migration خرید.

**نکته:** وضعیت «کدنویسی‌شده» با «PASS» فرق دارد. بدون اجرای تست‌ها هیچ مسیر Production-ready نیست.
