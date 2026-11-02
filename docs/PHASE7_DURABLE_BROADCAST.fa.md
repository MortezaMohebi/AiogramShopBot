# فاز ۷ — Broadcast خودکار با صف پایدار و محدودیت نرخ Telegram/Bale

**وضعیت:** SOURCE-IMPLEMENTED / NOT LIVE-TESTED. این فاز روی Draft PR نوشته شده؛
هیچ پیام واقعی، API هزینه‌دار، دیتابیس عملیاتی یا Worker واقعی اجرا نشده است.
مطابق تصمیم پروژه، تست و دیباگ نهایی به انتهای توسعه موکول شده‌اند.

## آخرین بازبینیِ مسیر ارسال

متد قدیمی `ShopCampaignService.dispatch_batch` که ارسال را داخل درخواست
داشبورد و بدون محدودیت نرخ پایدار انجام می‌داد، از مسیر اجرایی حذف شد.
داشبورد تنها تصمیم شروع و مدیریت وضعیت را ذخیره می‌کند و Worker مستقل
صاحب اجرای واقعی است. تست‌های قدیمی به Snapshot تأیید/رسانه و تست‌های
جدید Worker به کارکرد واقعی صف اختصاص داده شده‌اند.

## تغییر معماری

صف کمپین `ShopCampaignDelivery` در PostgreSQL باقی می‌ماند. مدیر یک‌بار
مخاطبان را تأیید می‌کند؛ سپس با یک تأیید دوم، کمپین را شروع می‌کند.
سرویس مشترک `workers.shop_broadcast` گیرنده‌ها را یکی‌یکی از صف قفل‌شده
می‌گیرد و تا پایان **تمام کاربران رضایت‌داده** ادامه می‌دهد. تعداد کل
مخاطبان محدود به Batch ده‌تایی نیست. Batch کوچک صرفاً برای کنترل منابع،
پاسخ‌گویی به دستور Pause و کاهش فشار بر دیتابیس است.

یک Worker برای یک نصب فروشگاه کافی است؛ به‌ازای هر مشتری Bot یا هر عضو کمپین
Container جداگانه ساخته نمی‌شود. PostgreSQL نقش Durable Queue را دارد و
برای اجرای ساده، RabbitMQ/Temporal/Celery جدیدی لازم نیست.

### نمودار متنی قابل تبدیل به دیاگرام

```text
Persian SQLAdmin (Marketing/Superadmin)
  -> Draft + Media -> Approve Audience
  -> Start [channel mode, explicit paid-message ceiling]
  -> PostgreSQL: Campaign(status=sending), Delivery(queued)
  -> shared broadcast-worker [one process, durable polling]
      -> PostgreSQL FOR UPDATE SKIP LOCKED claim one recipient
      -> recheck consent + campaign state
      -> PostgreSQL rate slots: bot-global + private-chat
      -> Telegram Adapter [Direct / Proxy / Cloudflare Worker]
         or Bale Adapter [Standard / approved paid Business]
      -> text and ordered file attachments
      -> persist completed_steps and sent/unknown/skipped receipt
      -> next queued recipient ... until no recipient remains
  -> SQLAdmin Progress + Pause / Resume / Cancel / Reconcile
```

## وضعیت‌های کمپین

| وضعیت | معنی |
|---|---|
| `draft` | متن و رسانه قابل ویرایش؛ ارسال ممنوع |
| `approved` | مخاطبان Opt-in ثبت شده‌اند؛ منتظر دستور شروع |
| `sending` | Worker به‌صورت خودکار صف را پیش می‌برد |
| `paused` | گیرنده جدید Claim نمی‌شود؛ ادامه فقط با تأیید مدیر |
| `needs_review` | صف تمام شده اما رسیدهای نامشخص باقی مانده‌اند |
| `completed` | همه گیرنده‌ها تعیین تکلیف شده‌اند |
| `cancelled` | باقی‌مانده صف Skip؛ ارسال‌های در حال انجام قابل Rollback نیست |

هر گیرنده یکی از `queued`، `sending`، `sent`، `unknown` یا `skipped`
را دارد. `completed_steps` تعداد پیام‌های تأیید‌شده همان گیرنده (متن و
تعداد فایل‌ها) را نشان می‌دهد. اگر بین متن و ویدیو اتصال قطع شود، وضعیت
`unknown` ثبت می‌شود و **ارسال خودکار مجدد ممنوع است**.

کمپین‌ها و تصمیم‌های مدیر در `ShopCampaignAudit` نگهداری می‌شوند.
گیرنده‌های `unknown` تنها با مدرک Provider و تأیید مدیر به `sent` یا
`skipped` تبدیل می‌شوند؛ **هیچ دکمه Retry بدون بررسی نداریم**.
برای ارسال مجدد واقعی، باید کمپین جدید با تأیید جداگانه ساخته شود.

## بازیابی پس از قطع سرویس

- Worker قبل از هر فراخوانی API یک Delivery را به `sending` تغییر می‌دهد.
- پس از پیام تأییدشده، `completed_steps` در دیتابیس Commit می‌شود.
- پس از Restart، تنها `queued`های باقی‌مانده ادامه می‌یابند.
- رکوردهای `sending` قدیمی‌تر از آستانه ۹۰۰ ثانیه به `unknown`
  منتقل و کمپین متوقف می‌شود. این روش At-most-once است، نه Exactly-once.
- Crash ممکن است باعث شود یک پیام واقعاً ارسال شود ولی رسید ثبت نشود؛
  برای جلوگیری از دوباره‌کاری و هزینه، چنین موردی خودکار بازپخش نمی‌شود.
- صفحه داشبورد با Heartbeat از جدول
  `shop_broadcast_worker_heartbeats`، فعال‌بودن Worker را نیز نشان می‌دهد.

## کنترل Rate Limit

هر پیام (متن، عکس، ویدیو، سند) مستقل از طریق
`ShopBroadcastRateSlot` برای `(platform, bot_fingerprint)` و
`(platform, bot_fingerprint, recipient_id)` نوبت دریافت می‌کند.
قفل PostgreSQL باعث می‌شود حتی در صورت اجرای چند Worker مشترک روی یک
دیتابیس، نرخ‌ها مستقل از تعداد Process رعایت شوند.

پیش‌فرض‌های محافظه‌کارانه:

| کانال | پیام در ثانیه برای هر Bot |
|---|---:|
| تلگرام عادی | ۵ |
| بله Standard | ۱ |
| بله Business | ۵ |
| یک چت خصوصی | حداکثر ۱ در ثانیه |

طبق [Telegram Bot FAQ](https://core.telegram.org/bots/faq)، سقف
Broadcast رایگان تلگرام حدود ۳۰ پیام در ثانیه است و برای هر چت خصوصی
بهتر است بیش از ۱ پیام در ثانیه ارسال نشود. نرخ واقعی API بله به شرایط
حساب و Provider بستگی دارد؛ مقادیر ۱ و ۵ پیش‌فرض‌های **مهندسی و محافظه‌کارانه**
هستند، نه ادعای سقف رسمی بله. تا آزمایش واقعی تغییرشان ندهید.

Rate Slotها پایدارند: اگر Worker Restart شود، زمان رزروشده قبلی حفظ می‌شود.
درخواست‌های `429` یا Timeout مبهم نیز به‌جای Retry کورکورانه، برای بررسی
ثبت و کمپین Pause می‌شوند.

## هزینه Business API بله

حالت Standard پیش‌فرض است و Business فقط با فعال‌سازی صریح کار می‌کند.

شروع Business نیازمند **هر چهار شرط** است:

1. `BALE_BROADCAST_MODE=business`
2. `BALE_BROADCAST_PAID_ENABLED=true`
3. `SHOP_BROADCAST_MAX_PAID_CALLS` بزرگ‌تر از صفر
4. مدیر در فرم شروع، عدد دقیق
   `Bale opted-in recipients × (1 + attachment_count)` را وارد کند
   و عبارت `START_PAID_BALE` را تأیید کند

عدد تأییدشده در `ShopCampaign.max_paid_calls` **ثابت** می‌ماند.
پیش از تک‌تک تماس‌های Business API مقدار
`paid_calls_reserved` با Lock دیتابیس یک واحد افزایش می‌یابد و
درخواست بعدی نمی‌تواند سقف را رد کند. رزرو حتی اگر پاسخ مبهم باشد آزاد
نمی‌شود تا از هزینه نامحدود جلوگیری شود.

برای فایل‌ها، پیش از شروع باید `file_id` معتبر همان بازو موجود باشد.
«آماده‌سازی رسانه» توسط مدیر و از طریق API عادی بله انجام می‌شود؛
Business API با فایل Multipart آغاز نمی‌شود. نرخ و هزینه نهایی فقط پس از
تست Provider و تأیید کاربر قابل استفاده‌اند.

## کنترل‌های راه‌اندازی (غیرفعال پیش‌فرض)

```env
SHOP_CAMPAIGN_DISPATCH_ENABLED=false
SHOP_BROADCAST_WORKER_ENABLED=false
SHOP_BROADCAST_TELEGRAM_MPS=5
SHOP_BROADCAST_BALE_STANDARD_MPS=1
SHOP_BROADCAST_BALE_BUSINESS_MPS=5
SHOP_BROADCAST_MAX_PAID_CALLS=0
SHOP_BROADCAST_POLL_SECONDS=2
SHOP_BROADCAST_STALE_SECONDS=900

BALE_BROADCAST_MODE=standard
BALE_BROADCAST_PAID_ENABLED=false
BALE_BROADCAST_PREPARE_CHAT_ID=0
```

پس از قبولی تست‌ها و Migration روی PostgreSQL آزمایشی، محیط اجرا در
Compose با یک سرویس مشترک اضافه می‌شود:

```bash
# Final acceptance ONLY: migrate an isolated DB with backup first.
alembic upgrade head

# After the admin and both Bot API providers have been verified:
docker compose --profile broadcast up -d broadcast-worker
```

سرویس `broadcast-worker` از همان Image برنامه استفاده می‌کند، ولی
هیچ Webhook/Ngrok یا Server HTTP را اجرا نمی‌کند. Volume خصوصی رسانه
با Bot مشترک است. برای Production باید Container اصلی Bot و PostgreSQL
نیز سالم باشند. اجرای دستی دستور بالا در این فاز انجام نشده است.

## محدوده تست‌های آماده‌شده

`tests/test_durable_broadcast_worker_offline.py`:
- یک تأیید و ارسال ۲۷ گیرنده، بدون کلیک مجدد مدیر؛
- Pause/Resume/Cancel و حفظ رسیدها؛
- Timeout، گیرنده `unknown` و عدم Retry خودکار؛
- Crash/Restart با Claim قدیمی؛
- Opt-out پس از Approval؛
- محدودیت هزینه Business API و Global/Per-chat Rate.

همچنین فایل‌های فاز ۶ برای MIME، API فایل بله، و Dedup Webhook
باقی مانده‌اند. **این تست‌ها نوشته شده‌اند ولی اجرا نشده‌اند.**
PostgreSQL `SKIP LOCKED`، Rate Slotهای واقعی، قطع ارتباط و هزینه API
در تست نهایی باید جدا آزمایش شوند.

## باقی‌مانده تا Production

- Test → Debug → Retest روی PostgreSQL/Redis و Botهای آزمایشی.
- تأیید نسخه واقعی مستندات Telegram/Bale و نرخ/سهمیه حساب مربوطه.
- ارزیابی تست‌های هم‌زمانی Worker و Shutdown وسط ارسال چندرسانه‌ای.
- بررسی امنیت CSRF، Staff Roles، سوءاستفاده از هزینه Business و Audit.
- مانیتورینگ ظرفیت رسانه و نگهداری فایل/Rate Slot در بلندمدت.

**در این فاز هیچ کمپینی به مشتریان واقعی ارسال یا پولی مصرف نشده است.**
