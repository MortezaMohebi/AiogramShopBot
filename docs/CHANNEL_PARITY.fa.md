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

### دستورهای Smoke Test پیشنهادی (در محیط دارای Dependency)

```bash
python -m compileall -q channels services/shop_channel_catalog.py
pytest -q tests/test_shop_channel_catalog.py tests/test_bale_channel_transport.py tests/test_telegram_channel_transport.py
alembic upgrade head
```

تست Migration باید در دیتابیس آزمایشی مستقل اجرا شود؛ دستور بالا روی دیتابیس اصلی بدون Backup مجاز نیست. فایل‌های تست از Network استفاده نمی‌کنند، اما به Dependencies واقعی پروژه نیاز دارند.

در Production، `WEBHOOK_HOST=https://your-domain.example` تنظیم شود تا نیازی به سرویس خارجی تشخیص IP نباشد. به‌دلیل وجود مسیر محرمانه بله، Access Log مربوط به URL باید در Reverse Proxy حذف یا Redact شود. کد فعلی در حالت Bale، Access Log داخلی Uvicorn را غیرفعال می‌کند.

## Telegram Cloudflare Worker mode

برای تنظیم حالت `cloudflare_worker` و روش دریافت `polling` یا `webhook`، راهنمای [Cloudflare Worker](CLOUDFLARE_WORKER.fa.md) را ببینید.
این Proxy فقط برای Telegram است و هیچ تغییری در مسیر API بله اعمال نمی‌کند.

## وضعیت واقعی فاز ۲

| قابلیت upstream تلگرام | بله در شاخه توسعه | پذیرش |
|---|---|---|
| کاتالوگ/دسته‌بندی/متن | Core مشترک | کدنویسی شد، بدون تست عملی |
| تصاویر/صوت/ویدیو/PDF | هر دو Transport از فایل خصوصی مشترک | کدنویسی شد، تست زنده باقی |
| رضایت مشتری | مشترک با تأیید انتشار | کدنویسی شد، تست زنده باقی |
| تاریخچه سفارش جدید | تفکیک `platform,user_id` | کدنویسی شد؛ Legacy ادغام نشده |
| پرداخت کیف پول بله | `sendInvoice`، `answerPreCheckoutQuery`، `inquireTransaction` | کدنویسی شد؛ پیش‌فرض خاموش |
| سبد خرید چندقلمی | موجود در Legacy تلگرام | هنوز برای بله منتقل نشده |
| ارسال و هزینه حمل | موجود در Legacy تلگرام | هنوز برای بله منتقل نشده |
| کد تخفیف | موجود در Legacy تلگرام | هنوز برای بله منتقل نشده |
| پیام همگانی و اعلان | موجود در Legacy تلگرام | هنوز برای بله منتقل نشده |
| Referral و اعتبار غیررمزارزی | موجود در Legacy تلگرام | هنوز برای بله منتقل نشده |
| Crypto و برداشت رمزارزی | Telegram Legacy | خارج از محدوده بله |

[جزئیات فاز ۲ و معیارهای باز](PHASE2_STATUS.fa.md)

## فاز ۳ — جایگزین وضعیت قدیمی Cart

در فاز جدید، Cart چندقلمی، افزایش/کاهش تعداد، انتخاب روش ارسال، دریافت نشانی،
Coupon، Quote، ثبت درخواست بدون پرداخت، تاریخچه و لغو در **Core مشترک** نوشته شده‌اند.
همه موارد بالا در Telegram و Bale به‌صورت موازی در کد متصل شده‌اند،
اما تست عملی انجام نشده است. جدول فاز ۲ در بالا، تصویر تاریخی وضعیت همان فاز است.

پرداخت Wallet بله و پرداخت Telegram هنوز به Cart چندقلمی جدید وصل نیستند؛
وضعیت `pending_review` به معنی دریافت وجه یا رزرو موجودی نیست.
[گزارش فاز ۳](PHASE3_SHARED_CHECKOUT.fa.md)

## فاز ۴: وضعیت کدنویسی پرداخت مشترک

| قابلیت | Telegram | Bale |
|---|---|---|
| پرداخت کالای فیزیکی | فاکتور Provider با IRR و ضریب ریزواحدِ تأییدشده | کیف پول رسمی IRR |
| پرداخت کالای دیجیتال | Stars با قیمت مستقل XTR | کیف پول رسمی IRR |
| تأیید مبلغ/مالکیت | `pre_checkout_query` | `pre_checkout_query` |
| سند پرداخت | `successful_payment` | `successful_payment` + `inquireTransaction` |
| کسر اتمیک چند قلم | `ShopPaymentService.settle` | همان Core |
| مصرف Coupon بعد از وصول | همان Core | همان Core |
| دریافت رسید تکراری | Idempotent | Idempotent |
| بازپرداخت | `refundStarPayment` برای Stars؛ فیات دستی | دستی با مدرک Provider (API رسمی تأیید نشده) |

**تمام موارد جدول صرفاً کدنویسی‌شده‌اند و Live PASS نیستند.**
[گزارش فاز ۴](PHASE4_PAYMENTS.fa.md)

## فاز ۵: برابری قابلیت‌های غیررمزارزی (فقط کد)

| قابلیت | Telegram | Bale |
|---|---|---|
| اعتبار داخلی ریالی و تاریخچه | `ShopWalletService` | همان Service |
| پرداخت کامل از اعتبار فروشگاهی | در تأیید دوم مشتری | همان هسته |
| بازپرداخت اعتبار داخلی | با رسید دفترکل و تصمیم مدیر | همان هسته |
| کد معرفی و Referral | کد مخصوص هویت Telegram | کد مخصوص هویت Bale |
| پاداش معرفی | اولین خرید Provider-IRR موفق | همان شرط |
| اطلاعیه همگانی | فقط Opt-in با `TelegramTransport` | فقط Opt-in با `BaleTransport` |
| گزارش‌های مدیریتی | تجمیع جداگانه IRR/XTR/Credit | IRR و Credit جدا |
| مدیریت کاربران و نقش‌ها | SQLAdmin مشترک | SQLAdmin مشترک |
| رمزارز و برداشت | Legacy تلگرام؛ اختیاری | عمداً پشتیبانی نمی‌شود |

**همه موارد بالایی کدنویسی شده و هنوز تست و Deploy نشده‌اند.** [گزارش فاز ۵](PHASE5_ENGAGEMENT.fa.md)

## فاز ۵ — توانمندی‌های غیررمزارزی جدید

کدهای Store Credit ریالی، Referral، Consent، Broadcast و Analytics در Core مشترک برای Telegram و Bale ثبت شده‌اند. این موارد تست API واقعی ندارند و Broadcast پیش‌فرض غیرفعال است. [جزئیات فاز ۵](PHASE5_PARITY.fa.md)

## فاز ۶ — فایل، Cache و Broadcast

| موضوع | Telegram | Bale |
|---|---|---|
| آپلود عکس | فایل اصلی خصوصی + Cache مخصوص Bot | حداکثر ۱۰ MB برای Multipart |
| ویدیو/صوت/PDF | رسانه اصلی و `file_id` مخصوص Bot | حداکثر ۵۰ MB برای Multipart |
| Voice OGG | مسیر صوتی یا Document | Voice تا ۱ MB؛ بزرگ‌تر Document |
| بازپخش فایل | `file_id` تلگرام همان Bot | `file_id` یکتای همان بازو |
| Broadcast متنی/فایلی | TelegramTransport | Bale Standard یا Business اختیاری |
| Broadcast پولی | ندارد | Business API با سهمیه بالاتر و هزینه هر پیام؛ فعال‌سازی جدا |
| دریافت Webhook تکراری | `ShopInboundUpdate` | همان Core با Bot Fingerprint مجزا |

**وضعیت:** کدنویسی‌شده، بدون اجرای عملی؛ Business پولی با Flag خاموش می‌ماند.
[جزئیات فاز ۶](PHASE6_MEDIA_BROADCAST.fa.md)
