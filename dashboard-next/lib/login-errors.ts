/** Safe, consistent Persian error messages for login and authentication. */
export type LoginErrorCode =
  | "invalid_credentials"
  | "temporarily_locked"
  | "service_unavailable"
  | "security_check_failed"
  | "invalid_request"
  | "captcha_required"
  | "captcha_failed"
  | "captcha_unavailable"
  | "network_unavailable"
  | "session_expired";

export interface LoginErrorMessage {
  title: string;
  description: string;
  canRetry: boolean;
}

/** Never return password, provider details, raw stack traces or private URLs. */
export const loginErrorMessages: Record<LoginErrorCode, LoginErrorMessage> = {
  invalid_credentials: {
    title: "ورود انجام نشد",
    description: "نام کاربری یا رمز عبور صحیح نیست. اطلاعات را بررسی و دوباره تلاش کنید.",
    canRetry: true,
  },
  temporarily_locked: {
    title: "تلاش‌های ورود بیش از حد مجاز است",
    description: "برای حفاظت از حساب، ورود موقتاً محدود شده است. کمی بعد دوباره تلاش کنید.",
    canRetry: false,
  },
  service_unavailable: {
    title: "سرویس ورود در دسترس نیست",
    description: "ارتباط با سرویس مدیریت برقرار نشد. وضعیت سرویس را بررسی و دوباره تلاش کنید.",
    canRetry: true,
  },
  security_check_failed: {
    title: "بررسی امنیتی ورود ناموفق بود",
    description: "جلسهٔ ورود معتبر نیست. صفحه را دوباره باز کنید و مطمئن شوید از آدرس اصلی داشبورد استفاده می‌کنید.",
    canRetry: true,
  },
  invalid_request: {
    title: "اطلاعات ورود ناقص است",
    description: "نام کاربری و رمز عبور را کامل و با قالب صحیح وارد کنید.",
    canRetry: true,
  },
  captcha_required: {
    title: "تأیید امنیتی لازم است",
    description: "بررسی امنیتی را کامل کنید و دوباره برای ورود تلاش کنید.",
    canRetry: true,
  },
  captcha_failed: {
    title: "تأیید امنیتی پذیرفته نشد",
    description: "بررسی امنیتی منقضی یا نامعتبر است. آن را دوباره انجام دهید.",
    canRetry: true,
  },
  captcha_unavailable: {
    title: "بررسی امنیتی در دسترس نیست",
    description: "سرویس تأیید امنیتی بارگذاری یا پاسخ‌دهی نشد. اتصال را بررسی کنید؛ در صورت تداوم با مدیر سامانه تماس بگیرید.",
    canRetry: true,
  },
  network_unavailable: {
    title: "ارتباط با سرور قطع شد",
    description: "اتصال شبکه یا Codespaces را بررسی و دوباره تلاش کنید. اطلاعات واردشده ذخیره نشده‌اند.",
    canRetry: true,
  },
  session_expired: {
    title: "نشست مدیریتی پایان یافته است",
    description: "برای ادامه، دوباره با حساب مدیریتی خود وارد شوید.",
    canRetry: true,
  },
};

const knownCodes = new Set<string>(Object.keys(loginErrorMessages));

/** Normalize old URL query codes and untrusted server responses. */
export function normalizeLoginError(value: unknown): LoginErrorCode {
  if (value === "credentials" || value === "locked" || value === "unavailable") {
    return {
      credentials: "invalid_credentials",
      locked: "temporarily_locked",
      unavailable: "service_unavailable",
    }[value] as LoginErrorCode;
  }
  return typeof value === "string" && knownCodes.has(value)
    ? (value as LoginErrorCode)
    : "service_unavailable";
}
