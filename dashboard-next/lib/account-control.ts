import { requestBrowserChallenge } from "@/lib/browser-challenge";

/** Shared Persian status messages; raw backend errors never reach the UI. */
const errors: Record<string, string> = {
  invalid_credentials: "رمز فعلی صحیح نیست.",
  invalid_verification: "کد تأیید معتبر نیست یا قبلاً استفاده شده است.",
  mfa_required: "کد برنامهٔ احراز هویت یا یکی از کدهای بازیابی را وارد کنید.",
  mfa_not_configured: "کلید رمزنگاری MFA در سرور تنظیم نشده است؛ راهنمای راه‌اندازی را بررسی کنید.",
  mfa_unavailable: "اطلاعات احراز هویت قابل خواندن نیست؛ کلید رمزنگاری سرور باید بررسی شود.",
  mfa_enrollment_expired: "زمان فعال‌سازی پایان یافته است؛ دوباره شروع کنید.",
  session_expired: "نشست پایان یافته است؛ دوباره وارد شوید.",
  permission_denied: "این حساب مجوز این عملیات را ندارد.",
  reauthentication_required: "برای این تغییر، در حساب من هویت خود را دوباره تأیید کنید.",
  connection_worker_unavailable: "سرویس اتصال آماده نیست؛ وضعیت سرور را بررسی کنید.",
  reconciliation_required: "نتیجهٔ عملیات مشخص نیست؛ پیش از تلاش دوباره، وضعیت اتصال را بررسی کنید.",
  invalid_request: "اطلاعات فرم معتبر نیست؛ فیلدها را بررسی کنید.",
  invalid_timezone: "منطقهٔ زمانی معتبر نیست؛ نمونه: Asia/Tehran.",
  username_unchanged: "نام کاربری جدید با نام فعلی یکسان است.",
  staff_username_exists: "این نام کاربری قبلاً ثبت شده است.",
  password_policy_failed: "رمز عبور با سیاست امنیتی فعلی مطابقت ندارد.",
  mfa_enrollment_required: "برای استفاده از این نقش ابتدا احراز هویت دومرحله‌ای را در حساب من فعال کنید.",
  mfa_required_by_role: "احراز هویت دومرحله‌ای برای این نقش اجباری است و قابل غیرفعال‌سازی نیست.",
  invitation_only: "ساخت حساب فقط با دعوت‌نامه امکان‌پذیر است.",
  invitation_not_found: "دعوت‌نامه یافت نشد یا قبلاً استفاده شده است.",
  invalid_link: "لینک نامعتبر، لغوشده یا منقضی شده است.",
  password_unchanged: "رمز تازه باید با رمز فعلی متفاوت باشد.",
  temporarily_locked: "تعداد تلاش‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید.",
  security_check_failed: "بررسی امنیتی ناموفق بود؛ صفحه را دوباره باز کنید.",
  connection_change_in_progress: "این اتصال یک تغییر باز یا نیازمند بررسی دارد؛ ابتدا آن را تعیین تکلیف کنید.",
  invalid_operation_state: "وضعیت عملیات تغییر کرده است؛ فهرست را تازه‌سازی کنید.",
  configuration_changed: "تنظیم فعال تغییر کرده است؛ درخواست تازه‌ای ایجاد کنید.",
};
export interface ControlResult { ok?: boolean; code?: string; login_required?: boolean; secret?: string; qr_data_uri?: string; recovery_codes?: string[]; token?: string; expires_at?: string }
/** Preserve the safe machine code for contextual recovery without raw messages. */
export class ControlActionError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "ControlActionError";
  }
}
/** Exact allowlisted route names are enforced again by the server. */
export async function controlAction(action: string, data: unknown): Promise<ControlResult> {
  let token: string;
  try {
    token = await requestBrowserChallenge();
  } catch {
    throw new Error("بررسی امنیتی انجام نشد. صفحه را دوباره باز کنید.");
  }
  const response = await fetch(`/api/account/${action}`, {
    method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Shop-Login-Challenge": token },
    body: JSON.stringify(data), signal: AbortSignal.timeout(25_000),
  }).catch(() => {
    // A lost response does not establish whether the change was applied.
    throw new Error("پاسخ نهایی دریافت نشد. پیش از تلاش دوباره، وضعیت فعلی را بررسی کنید.");
  });
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new Error("پاسخ سرویس معتبر نیست؛ اتصال را بررسی کنید.");
  const value: unknown = await response.json().catch(() => {
    throw new Error("پاسخ نهایی قابل خواندن نیست. پیش از تلاش دوباره، وضعیت فعلی را بررسی کنید.");
  });
  if (!value || typeof value !== "object") throw new Error("پاسخ سرویس معتبر نیست.");
  const result = value as ControlResult;
  if (!response.ok || result.ok !== true) {
    const code = typeof result.code === "string" ? result.code : "";
    throw new ControlActionError(code, errors[code] ?? "عملیات کامل نشد؛ وضعیت فعلی را بررسی و سپس دوباره تلاش کنید.");
  }
  return result;
}
export interface AccountData {
  username: string; role: string; display_name: string; time_zone: string; mfa_enabled: boolean; mfa_required_by_role: boolean; password_policy: { min_length: number; require_upper: boolean; require_lower: boolean; require_digit: boolean; require_symbol: boolean };
  preferences: {
    language: "fa" | "en";
    calendar: "auto" | "jalali" | "gregorian";
    notify_orders: boolean;
    notify_campaigns: boolean;
    notify_finance: boolean;
    notify_system: boolean;
  };
  permissions: string[];
  sessions: { id: string; label: string; current: boolean; created_at: string; last_seen_at: string; expires_at: string; revoked: boolean; active: boolean }[];
  events: { id: string; action: string; created_at: string }[];
}
export const permissionLabels: Record<string, string> = {
  "account.manage_self": "مدیریت حساب شخصی", "dashboard.read": "مشاهده نمای کلی",
  "catalog.read": "مشاهده محصولات", "catalog.write": "ویرایش محصولات", "media.manage": "مدیریت رسانه",
  "customers.read": "مشاهده مشتریان", "orders.read": "مشاهده سفارش‌ها", "orders.manage": "بررسی سفارش",
  "shipping.manage": "تنظیم روش ارسال", "coupons.manage": "مدیریت تخفیف", "finance.read": "مشاهده اطلاعات مالی",
  "wallet.adjust": "اصلاح اعتبار داخلی", "refund.execute": "اجرای بازپرداخت", "reports.read": "مشاهده گزارش",
  "campaigns.manage": "آماده‌سازی کمپین", "broadcast.approve": "تأیید ارسال انبوه", "staff.manage": "مدیریت کارکنان",
  "settings.manage": "تنظیم فروشگاه", "bots.read": "مشاهده اتصال ربات‌ها", "bots.configure": "ثبت تغییر اتصال",
  "bots.apply": "اعمال تغییر اتصال", "audit.read": "مشاهده رویدادهای مدیریتی",
};
