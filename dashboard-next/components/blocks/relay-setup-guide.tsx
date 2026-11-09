import Link from "next/link";
import { ChevronDown } from "lucide-react";

const deploy = "cd cloudflare/telegram-relay\nnpx wrangler login\nnpx wrangler deploy --name relay-name";
const secret = "npx wrangler secret put RELAY_CLIENTS_JSON --name relay-name";
const example = `{
  "00000000-0000-4000-8000-000000000101": {
    "token_sha256": "<sha256-hex>",
    "keys": { "1": "<relay-key>" },
    "rps": 5,
    "max_inflight": 10
  }
}`;
const commandStyle = "overflow-x-auto rounded-md bg-muted p-3 text-left text-xs";

export function RelaySetupGuide() {
  return <details id="relay-setup" className="group rounded-xl border bg-card">
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-xl p-4 font-medium [&::-webkit-details-marker]:hidden">
      راهنمای ساخت و اتصال Relay
      <ChevronDown className="size-4 shrink-0 motion-safe:transition-transform group-open:rotate-180" aria-hidden="true" />
    </summary>
    <ol className="list-decimal space-y-4 border-t py-4 ps-9 pe-4 text-sm leading-7">
      <li className="space-y-2">
        <h3 className="font-semibold">Worker را در Cloudflare مستقر کنید</h3>
        <p>از پوشهٔ Worker پروژه استفاده کنید. یک نام یکتا به‌جای <code dir="ltr">relay-name</code> بگذارید
          تا همان تنظیمات سهمیه و Durable Object با نام <code dir="ltr">RELAY_QUOTA</code> مستقر شوند.</p>
        <pre dir="ltr" className={commandStyle}><code>{deploy}</code></pre>
      </li>
      <li className="space-y-2">
        <h3 className="font-semibold">نشانی Worker را در سرور مجاز و در داشبورد ثبت کنید</h3>
        <p>نشانی پایهٔ HTTPS را به <code dir="ltr">TELEGRAM_WORKER_ALLOWED_ORIGINS</code> اضافه کنید
          و تنظیمات سرویس را دوباره اعمال کنید. نشانی‌ها با ویرگول جدا می‌شوند.
          در «Worker جدید»، نشانی را بدون مسیر یا پارامتر وارد کنید.</p>
      </li>
      <li className="space-y-2">
        <h3 className="font-semibold">مسیر تلگرام و کلید را آماده کنید</h3>
        <p>از <Link href="/bots" className="text-primary underline">مدیریت ربات‌ها</Link>، یک ربات تلگرام تأییدشده را باز کنید.
          در «مسیرهای Relay ربات»، Worker را اضافه و رکورد مسیر را باز کنید.
          در «کلید اتصال»، یک کلید تصادفی مستقل با ۳۲ تا ۲۵۶ نویسهٔ چاپ‌پذیر ASCII ثبت کنید.
          UUID ربات و شمارهٔ نسخهٔ کلید را برای مرحلهٔ بعد بردارید.</p>
      </li>
      <li className="space-y-2">
        <h3 className="font-semibold">Secret همان Worker را تنظیم کنید</h3>
        <p>در نمونهٔ زیر UUID، هش SHA-256 توکن تلگرام به صورت هگز کوچک، شمارهٔ نسخه و همان کلید را جایگزین کنید.
          هش را محلی محاسبه کنید و JSON یک‌خطی را از ورودی محرمانهٔ Wrangler وارد کنید.
          برای Worker مشترک، ورودی‌های ربات‌های دیگر را هم در JSON حفظ کنید.</p>
        <pre dir="ltr" className={commandStyle}><code>{example}</code></pre>
        <pre dir="ltr" className={commandStyle}><code>{secret}</code></pre>
        <p>مقادیر واقعی را فقط در محل ثبت کلید و Secret نگه دارید.</p>
        <a className="text-primary underline" href="https://developers.cloudflare.com/workers/configuration/secrets/">
          مستندات Secret در Cloudflare
        </a>
      </li>
      <li className="space-y-2">
        <h3 className="font-semibold">مسیر را با getMe بررسی کنید</h3>
        <p>در <Link href="/services" className="text-primary underline">سرویس‌ها</Link>، «اتصال‌های Relay تلگرام» را فعال کنید.
          در رکورد مسیر، «آزمون و فعال‌سازی» را بزنید و رمز فعلی را وارد کنید.
          با تطبیق شناسهٔ ربات، مسیر و Worker فعال می‌شوند. getMe فقط اطلاعات ربات را می‌خواند.</p>
        <p>اگر تأیید ناموفق بود، نشانی مجاز، UUID، هش توکن، نسخهٔ کلید و Binding سهمیه را بررسی کنید.</p>
      </li>
    </ol>
  </details>;
}
