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
  reauthentication_required: "برای این عملیات، در بخش امنیت رمز فعلی خود را دوباره تأیید کنید.",
  connection_worker_unavailable: "پردازشگر اتصال آماده نیست؛ سلامت Backend را بررسی کنید.",
  reconciliation_required: "نتیجه نامشخص است؛ ابتدا وضعیت Provider را تطبیق دهید.",
  invalid_request: "اطلاعات فرم معتبر نیست؛ فیلدها را بررسی کنید.",
  invalid_timezone: "منطقهٔ زمانی معتبر نیست؛ نمونه: Asia/Tehran.",
  password_unchanged: "رمز تازه باید با رمز فعلی متفاوت باشد.",
  temporarily_locked: "تعداد تلاش‌ها بیش از حد مجاز است؛ کمی بعد دوباره تلاش کنید.",
  security_check_failed: "بررسی امنیتی ناموفق بود؛ صفحه را دوباره باز کنید.",
  connection_change_in_progress: "این اتصال یک تغییر باز یا نیازمند بررسی دارد؛ ابتدا آن را تعیین تکلیف کنید.",
  invalid_operation_state: "وضعیت عملیات تغییر کرده است؛ فهرست را تازه‌سازی کنید.",
  configuration_changed: "تنظیم فعال تغییر کرده است؛ درخواست تازه‌ای ایجاد کنید.",
};
export interface ControlResult { ok?: boolean; code?: string; login_required?: boolean; secret?: string; recovery_codes?: string[] }
/** Exact allowlisted route names are enforced again by the server. */
export async function controlAction(action: string, data: unknown): Promise<ControlResult> {
  const token = await requestBrowserChallenge();
  const response = await fetch(`/api/account/${action}`, {
    method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
    headers: { "Content-Type": "application/json", Accept: "application/json", "X-Shop-Login-Challenge": token },
    body: JSON.stringify(data), signal: AbortSignal.timeout(25_000),
  });
  if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new Error("پاسخ سرویس معتبر نیست؛ اتصال را بررسی کنید.");
  const value: unknown = await response.json();
  if (!value || typeof value !== "object") throw new Error("پاسخ سرویس معتبر نیست.");
  const result = value as ControlResult;
  if (!response.ok || result.ok !== true) throw new Error(errors[result.code ?? ""] ?? "عملیات کامل نشد؛ وضعیت فعلی را بررسی و سپس دوباره تلاش کنید.");
  return result;
}
export interface AccountData {
  username: string; role: string; display_name: string; time_zone: string; mfa_enabled: boolean;
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
