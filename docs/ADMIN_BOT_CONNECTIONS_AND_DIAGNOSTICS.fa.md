# مدیریت اتصال هر ربات

مسیرهای فعلی Dashboard: `/bots` و `/bots/{id}`. کنترل سراسری دو ربات، Token محیطی و صفحهٔ `/bot-connections` بازنشسته شده‌اند.

هر ربات Store، Credential رمزگذاری‌شده، Provider identity، نسخهٔ تنظیمات، Receiver، Relay و سیاست دسترسی مستقل دارد. ایجاد Draft هیچ پیام یا درخواست مالی ارسال نمی‌کند. Stage/Verify/Activate به Session معتبر، نقش مجاز، StoreContext و احراز هویت مجدد نیاز دارند.

برای عیب‌یابی، شناسهٔ درخواست و وضعیت همان ربات را بررسی کنید. نتیجهٔ ارسال نامعلوم به Review می‌رود و نباید بدون تطبیق دوباره ارسال شود. Verify باید هویت همان Token و نسخهٔ بررسی‌شده را تأیید کند؛ نتیجهٔ تب یا نسخهٔ قدیمی مجوز فعال‌سازی نیست.

Gateway فقط `POST /webhooks/v2/…` را به Receiver می‌رساند. Dashboard و API داخلی از Gateway در دسترس نیستند. برای مراحل Setup، [راهنمای Codespaces](CODESPACES_LIVE_SETUP.fa.md) را ببینید.
