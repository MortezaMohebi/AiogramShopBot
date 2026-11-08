/** Safe, human-readable messages for signed administrative file uploads. */
const uploadFailures: Readonly<Record<string, string>> = {
  security: "بررسی امنیتی درخواست انجام نشد. صفحه را دوباره باز و بارگذاری را تکرار کنید.",
  permission: "این حساب اجازهٔ بارگذاری در این بخش را ندارد. سطح دسترسی را بررسی کنید.",
  size: "حجم فایل از محدودیت مجاز بیشتر است. تصاویر حداکثر ۱۰ و سایر فایل‌ها حداکثر ۵۰ مگابایت هستند.",
  file: "فرمت فایل یا اطلاعات همراه آن معتبر نیست. نوع فایل و فیلدهای اجباری را بررسی کنید.",
  upload: "بارگذاری کامل نشد. ارتباط با سرویس رسانه یا وضعیت فایل را بررسی کنید.",
};

/** Map server-generated, allowlisted codes without exposing raw API errors. */
export function uploadErrorMessage(
  code: string | undefined,
  fallback: string,
): string {
  if (!code) return fallback;
  return Object.hasOwn(uploadFailures, code)
    ? uploadFailures[code]
    : fallback;
}
