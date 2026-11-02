# فاز ۶ — محدودیت رسانه، Cache هر بازو و Broadcast دوکاناله

**وضعیت:** کدنویسی روی شاخه Draft ثبت شده است؛ بدون Deploy، اجرای Bot، ارسال واقعی،
تست PostgreSQL یا فعال‌کردن سرویس پولی. این سند معیار پذیرش نهایی را مشخص می‌کند.

## سقف‌های رسمی Bale Bot API

منبع مستقیم: [docs.bale.ai — ارسال فایل‌ها](https://docs.bale.ai/)

| مسیر ارسال | عکس | سایر رسانه‌ها |
|---|---:|---:|
| آپلود مستقیم multipart/form-data | ۱۰ MB | ۵۰ MB |
| ارسال از HTTP URL | ۵ MB | ۲۰ MB |
| ارسال مجدد با file_id معتبر همان بازو | بدون آپلود | بدون آپلود |

در کد، MB با عدد صحیح **۱٬۰۰۰٬۰۰۰ بایت** سنجیده می‌شود؛
۱۰ MB = ۱۰٬۰۰۰٬۰۰۰ بایت و ۵۰ MB = ۵۰٬۰۰۰٬۰۰۰ بایت.
برای جلوگیری از ارسال نشدن فایل در بله، فایل عکس بزرگ‌تر از سقف
از ابتدای Upload داشبورد پذیرفته نمی‌شود، نه پس از نمایش به مشتری.
سایر فایل‌ها تا سقف جداگانه مجازند. این اعداد از تنظیم محیطی نمی‌توانند
بیش از سقف رسمی بالاتر بروند.

- عکس: `sendPhoto` با سقف مستقیم ۱۰ MB.
- MP4: `sendVideo` تا ۵۰ MB.
- MP3: `sendAudio` تا ۵۰ MB.
- OGG: `sendVoice` تا ۱ MB؛ فایل‌های OGG بزرگ‌تر به‌صورت
  `sendDocument` ارسال می‌شوند.
- PDF، GIF و دیگر انواع Document پشتیبانی‌شده: تا ۵۰ MB.
- Upload تنها در فضای خصوصی `SHOP_MEDIA_ROOT` نگهداری می‌شود.
  مسیر اصلی رسانه را `file_id` پیام‌رسان جایگزین نمی‌کند.

## Cache فایل به تفکیک Platform و Bot

`ShopRemoteFile` کلید یکتای
`(platform, bot_fingerprint, storage_key, delivery_kind)`
دارد. Fingerprint از SHA-256 توکن Bot ساخته می‌شود؛ متن توکن و شناسه‌های
بله/تلگرام هرگز با هم اشتراک داده نمی‌شوند.

بعد از آپلود موفق، از پاسخ معتبر Bot API شناسه `file_id` ذخیره می‌شود؛
دفعات بعد همان ربات از شناسه خودش استفاده می‌کند.
اگر Cache به‌روزرسانی نشد، پیام تأیید‌شده قبلی دوباره ارسال نمی‌شود.
فایل‌هایی که نوع ارسالشان عوض می‌شود یک Cache مجزا دارند.

## Broadcast

`ShopCampaign` و `ShopCampaignMedia` از داشبورد با متن، مخاطب هدف
(`telegram` / `bale` / `all`) و تعداد متغیر فایل تعریف می‌شوند.
فایل‌ها پیش از تأیید، از صفحه
`/admin/campaign-media-upload`
با Role بازاریابی و CSRF به کمپین Draft اضافه می‌شوند.
بعد از تأیید مخاطب، تغییر فایل مجاز نیست.

- فقط کاربرانی با رضایت صریح `allow_announcements=true` و بدون مسدودیت
  وارد صف ارسال می‌شوند. بله و تلگرام از Adapter مستقل استفاده می‌کنند.
- قبل از هر ارسال، وضعیت رضایت دوباره کنترل می‌شود.
- هر Batch حداکثر ۱۰ مخاطب دارد؛ **تعداد کل مخاطبان محدود به ۱۰ نفر نیست**.
  برای هر Batch اقدام مدیر لازم است؛ هنوز Scheduler خودکار فعال نشده است.
- متن و رسانه‌های مرتب‌شده از فضای خصوصی برای هر مخاطب ارسال می‌شوند.
  اگر بخشی از پیام یا رسانه ارسال شد ولی ادامه شکست، وضعیت `unknown`
  نگهداری می‌شود و Retry کورکورانه انجام نمی‌شود.
- پیش از شروع Batch، اصل فایل و سقف‌های حجم کنترل می‌شوند. کمپین دارای
  فایل بزرگ‌تر یا رسانه ناموجود، اجازه شروع ارسال ندارد.
- کنترل اصلی `SHOP_CAMPAIGN_DISPATCH_ENABLED=false` است.
  بدون روشن‌کردن صریح، هیچ کمپینی ارسال نمی‌شود.

## دو حالت ارسال به بله

| حالت | آدرس و رفتار | پیش‌فرض |
|---|---|---|
| `standard` | `https://tapi.bale.ai/bot<TOKEN>/...` با محدودیت تعامل و Rate Limit معمول | فعال به‌عنوان Mode |
| `business` | `https://tapi.bale.ai/business/bot<TOKEN>/...` با سهمیه بالاتر و **هزینه هر پیام** | غیرفعال تا رضایت صریح |

طبق مستندات رسمی بله، Business API تنها از متدهای
`getMe`، `sendMessage`، `sendPhoto`، `sendVideo`،
`sendDocument` و `sendAudio` پشتیبانی می‌کند.
در متدهای رسانه‌ای **فقط file_id** مجاز است و Multipart/URL مجاز نیست.

برای این موضوع، دکمه «آماده‌سازی رسانه بله» در صفحه کمپین اضافه شده:
با تأیید مدیر، فایل‌ها یک‌بار با Bot API عادی به **چت خصوصی مدیر**
(`BALE_BROADCAST_PREPARE_CHAT_ID`) فرستاده و IDهای تأییدشده Cache
می‌شوند. سپس قبل از اولین دریافت‌کننده پولی، وجود تمام IDهای لازم
کنترل می‌شود. `sendVoice` در Business API مجاز نیست.
**هیچ ارسال پولی بدون فعال‌سازی مستقل
`BALE_BROADCAST_PAID_ENABLED=true` مجاز نیست.**

```env
SHOP_MEDIA_MAX_BYTES=50000000
SHOP_CAMPAIGN_DISPATCH_ENABLED=false
BALE_BROADCAST_MODE=standard
BALE_BROADCAST_PAID_ENABLED=false
BALE_BROADCAST_PREPARE_CHAT_ID=0
```

هزینه ارسال Business API در این مخزن تخمین زده یا از فروشگاه کسر نمی‌شود؛
وضعیت اعتبار حساب Business باید در پنل رسمی بله بررسی شود.

## دریافت Webhook بدون دوباره‌کاری

`ShopInboundUpdate` هر `update_id` را به تفکیک Platform و Fingerprint
توکن نگهداری می‌کند: `processing`، `processed` و `needs_review`.
قبل از ارسال هر پاسخ یا ثبت عملیات، Update ثبت می‌شود؛ موارد تکراری
دوباره پردازش نمی‌شوند.

اگر پس از Claim خطای غیرمنتظره رخ دهد، رسید در وضعیت `needs_review`
نگهداری می‌شود. بعد از Crash ممکن است `processing` باقی بماند؛
این رکوردها باید دستی بررسی شوند، نه اینکه یک پرداخت یا پیام احتمالاً
ارسال‌شده دوباره اجرا شود.
پرداخت‌های Telegram/Bale همچنان علاوه بر این لایه از کلید یکتا و
تطبیق رسید Provider استفاده می‌کنند.

## Test Cases آماده‌شده (اجرا نشده)

- `tests/test_bale_media_limits.py`
- `tests/test_shop_broadcast_media_offline.py`
- `tests/test_bale_business_broadcast_offline.py`
- `tests/test_shop_delivery_dedup_offline.py`

## پذیرش نهایی

- نصب و اجرای Migration `20261103e001_media_delivery.py` و Rollback روی DB آزمایشی.
- تست واقعی مرز ۱۰/۵۰ MB، دانلود/آپلود، `sendVoice` و ارسال PDF/MP4.
- تأیید معتبر بودن file_id پس از ری‌استارت، تغییر توکن و چند Bot.
- تست دو Webhook هم‌زمان با update_id یکسان و Restart در حین ارسال.
- تست Opt-in/Opt-out، کمپین چندرسانه‌ای، Crash در حین ارسال، کنترل
  `unknown` و محافظت از هزینه‌های Business API.
- اندازه‌گیری Rate Limit واقعی Standard/Business و انتخاب نرخ ارسال امن.
- بررسی CDN/Proxy و گزارش‌های حساس بدون افشای Token و مسیر محرمانه.
- ادغام نکردن در master تا چرخه Test → Debug → Retest با PASS واقعی.

**انتشار عمومی و فعال‌سازی Broadcast پولی به مرحله نهایی موکول است.**
