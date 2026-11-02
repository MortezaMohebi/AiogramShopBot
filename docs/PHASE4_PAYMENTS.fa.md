# فاز ۴: پرداخت و بازپرداخت مشترک Telegram / Bale

**وضعیت: کدنویسی ثبت‌شده، نه تأیید عملیاتی.** هیچ Bot واقعی، پرداخت، انتقال وجه،
Migration، آزمایش PostgreSQL، یا اجرای کد مرتبط در محیط اصلی انجام نشده است.
طبق تصمیم پروژه تمام مراحل اجرای واقعی، تست و دیباگ به انتهای توسعه موکول شده‌اند.

## مدل پرداخت

- `ShopPaymentAttempt`: یک فاکتور یکتا برای هر `ShopOrder`، با `payload`
  تصادفی، ارز، مبلغ در کوچک‌ترین واحد API، Provider و وضعیت ارسال.
- `ShopOrder` پس از تأیید مدیریتی `approved_unpaid` است؛ انتخاب «پرداخت»
  فاکتور مستقل می‌سازد و وضعیت را `pending_payment` می‌کند.
- فاکتور فقط یک‌بار قابل ایجاد است. اگر ارسال API با خطا یا Timeout مواجه شد،
  وضعیت `dispatch_unknown` ثبت می‌شود؛ **ارسال مجدد خودکار ممنوع** است.
- `pre_checkout_query` فقط مالکیت حساب، ارز، مبلغ، `payload`، موجودی و
  ظرفیت تخفیف را بررسی می‌کند؛ دریافت پول یا کسر موجودی نیست.
- ثبت نهایی فقط با `successful_payment` ارائه‌شده توسط Adapter دارای Webhook
  معتبر Telegram / Bale انجام می‌شود. در بله، متد مستقل
  `inquireTransaction` باید `paid` و شناسه، مبلغ و کاربر یکسان برگرداند.
- با Lock ردیف Order و هر Product و Coupon، تمام اقلام یک سفارش به‌صورت
  اتمیک از موجودی کم و کد تخفیف **فقط یک‌بار** مصرف می‌شود.
- اگر پس از پرداخت، حتی یکی از اقلام یا ظرفیت Coupon کافی نباشد،
  **هیچ قلمی کسر نمی‌شود** و وضعیت `paid_unfulfilled` به همراه
  پرونده بازپرداخت/رسیدگی ثبت می‌شود.
- همان Receipt اگر دوباره دریافت شود، سفارش و موجودی را دوباره تغییر نمی‌دهد.

## ارز و نوع کالا

| نوع خرید | واحد ذخیره قیمت کالا | واحد پرداخت | شرط فعال‌سازی |
|---|---|---|---|
| بله (کالای فیزیکی یا دیجیتال) | IRR صحیح | IRR صحیح | `BALE_WALLET_CHECKOUT_ENABLED` و توکن |
| تلگرام فیزیکی | IRR صحیح | IRR با ضریب ریزواحد Provider | `TELEGRAM_FIAT_CHECKOUT_ENABLED` + توکن + ضریب معتبر |
| تلگرام دیجیتال | IRR برای مرجع فروشگاه، `price_stars` جدا | Stars (`XTR`) صحیح | `TELEGRAM_STARS_CHECKOUT_ENABLED` + قیمت Stars همه اقلام |

- در تلگرام فاکتور ترکیبی دیجیتال/فیزیکی مجاز نیست؛ کالاها باید در سفارش‌های
  جدا پرداخت شوند.
- تخفیف ریالی، هزینه ارسال و ارز IRR را به‌صورت خودکار به Stars تبدیل نمی‌کنیم.
  فاکتور Stars فقط وقتی تمام اقلام دیجیتال باشند و هیچ تخفیف/ارسال ریالی
  در سفارش نباشد صادر می‌شود.
- در فاکتور تلگرام ارز فیات، مقدار `LabeledPrice.amount` باید واحد کوچک
  پرداخت باشد، **نه تومان**. `TELEGRAM_IRR_MINOR_MULTIPLIER=0` پیش‌فرض
  است و تا تأیید واقعی درگاه، صدور فاکتور را مسدود می‌کند.
- `IRR` واحد اصلی دیتابیس است؛ `SHOP_DISPLAY_UNIT=TOMAN` فقط متن را تغییر می‌دهد.

## بازپرداخت

- مشتری از «سفارش‌های من» می‌تواند درخواست بازپرداخت برای سفارش
  `paid` یا `paid_unfulfilled` ایجاد کند.
- هر سفارش فقط یک `ShopRefundCase` دارد؛ مسئول فروشگاه آن را در
  صفحه `/admin/refund-review` بررسی می‌کند.
- **Telegram Stars:** فقط با Flag مستقل
  `TELEGRAM_STARS_REFUNDS_ENABLED=true` و اقدام تأییدشدهٔ مدیر،
  متد رسمی `refundStarPayment` فراخوانی می‌شود. قبل از فراخوانی وضعیت
  `provider_pending` ثبت می‌شود؛ Timeout نباید باعث اجرای مجدد کورکورانه شود.
- **بله و Telegram Fiat:** در اسنپ‌شات Bot API، مسیر بازپرداخت خودکار معتبر
  و تأییدشده‌ای برای این اتصال نداریم. ابتدا بازپرداخت در پنل رسمی Provider
  انجام و استعلام می‌شود، سپس مدیر شماره پیگیری را به‌عنوان سند ثبت می‌کند.
  ثبت این سند به‌تنهایی پول را جابه‌جا نمی‌کند.
- پس از **تأیید واقعی Provider یا بازپرداخت رسمی Stars** وضعیت
  `refunded` ثبت می‌شود؛ موجودی کالای احتمالاً تحویل‌شده به‌صورت خودکار
  برنمی‌گردد و مصرف کد تخفیف بدون تصمیم تجاری معکوس نمی‌شود.

## تنظیمات امن (پیش‌فرض خاموش)

```env
BALE_WALLET_CHECKOUT_ENABLED=false
BALE_WALLET_PROVIDER_TOKEN=
TELEGRAM_FIAT_CHECKOUT_ENABLED=false
TELEGRAM_FIAT_PROVIDER_TOKEN=
TELEGRAM_IRR_MINOR_MULTIPLIER=0
TELEGRAM_STARS_CHECKOUT_ENABLED=false
TELEGRAM_STARS_REFUNDS_ENABLED=false
```

توکن‌ها فقط در Secretهای سرور ذخیره می‌شوند؛ هیچ توکنی در Git یا مثال واقعی
قرار نگرفته است. فعال‌کردن Flag بدون تست و دریافت توکن Provider ممنوع است.

## مسیرهای کد

- `models/shop_payment.py`: PaymentAttempt و RefundCase با Viewهای فقط خواندنی.
- `migrations/versions/20261102c001_shared_payments.py`: Migration افزایشی.
- `services/shop_payments.py`: قفل سفارش، مبلغ immutable، pre-checkout،
  تسویه چندقلمی، تخصیص اتمیک موجودی و Coupon و RefundCase در کمبود موجودی.
- `channels/shop_payment_dispatch.py`: صدور فاکتور از طریق Aiogram یا Bale.
- `services/shop_bale_payments.py`: انطباق مستقل `inquireTransaction`
  با receipt و محافظت از جریان Legacy قدیمی.
- `channels/telegram_handlers.py`: PreCheckoutQuery، SuccessfulPayment و
  دکمه پرداخت سفارش مشترک.
- `services/shop_refunds.py`: پرونده Refund و متد رسمی Stars + مسیر دستی.
- `dashboard/refund_views.py`: فرم CSRF بازپرداخت و ثبت مدرک واقعی.
- `tests/test_shared_payment_settlement.py`: آزمون‌های Offline
  با DB موقت، بدون API واقعی.

## محدودیت‌ها و معیار پذیرش نهایی

1. درگاه حقیقی تلگرام باید واقعاً از IRR و ضریب ریزواحد آن پشتیبانی کند.
2. سازگاری متدهای `sendInvoice`، `pre_checkout_query`،
   `successful_payment` و `refundStarPayment` با Bot API و نسخه Aiogram
   به‌صورت زنده تأیید شود.
3. سناریوهای قطع اتصال، رسید تکراری، کد تخفیف پرشده، هم‌زمانی چند سفارش،
   تأیید مجدد، بازپرداخت و `paid_unfulfilled` روی PostgreSQL تست شوند.
4. رسانه‌ها، Dashboard RTL، Webhook Secret، و Cloudflare Worker تست شوند.
5. رفع حالت `dispatch_unknown` و بررسی موارد وصولِ نامشخص توسط مدیر
   به یک مسیر عملیاتی امن و قابل ممیزی نیاز دارد.
6. قابلیت‌های Legacy غیررمزارزی مانند Referral، Broadcast و Credit
   همچنان باید در فازهای بعدی به هسته مشترک منتقل شوند.
7. خروجی `pytest` و اجرای Migration در **این مرحله موجود نیستند**؛
   بنابراین PR برای Merge و پرداخت واقعی آماده نیست.

**مراجع:** سند بارگذاری‌شده Bot API Telegram/Bale در ۲۰۲۶-۱۱-۰۲؛
مستندات رسمی [Telegram Stars](https://core.telegram.org/bots/payments-stars)
و [Telegram payments](https://core.telegram.org/bots/payments).
