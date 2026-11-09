/** Redacted contracts for the many-to-many outbound Worker registry. */

export interface RelayWorker {
  id: string;
  slug: string;
  name: string;
  origin: string;
  status: "draft" | "active" | "paused" | "disabled";
  max_rps: number;
  max_inflight: number;
  version: number;
  bot_count: number;
  updated_at: string | null;
}

export interface RelayWorkersSnapshot {
  items: RelayWorker[];
  enabled: boolean;
  approved_origins: string[];
}

export interface BotRelayRoute {
  bot_id: string;
  worker_id: string;
  worker_name: string;
  worker_status: RelayWorker["status"];
  priority: number;
  status: "staged" | "active" | "paused";
  version: number;
  credential_version: number | null;
  credential_state: "staged" | "active" | "retiring" | "revoked" | null;
  credential_verified_at: string | null;
  credential_history: {
    version: number;
    state: "staged" | "active" | "retiring" | "revoked";
    verified_at: string | null;
  }[];
}

export interface BotRelaySnapshot {
  bot_id: string;
  items: BotRelayRoute[];
}

export const relayWorkerLabels: Record<string, string> = {
  draft: "پیش‌نویس", active: "فعال", paused: "متوقف", disabled: "غیرفعال",
};

export function relayRouteLabel(route: BotRelayRoute, serviceEnabled: boolean) {
  if (route.status === "paused") return "متوقف";
  if (route.status === "active") {
    return serviceEnabled && route.worker_status === "active" ? "متصل" : "تأییدشده، خارج از سرویس";
  }
  return route.credential_state === "staged" ? "آمادهٔ آزمون" : "در انتظار کلید";
}

const relayMessages: Record<string, string> = {
  validation: "فیلدهای فرم را بررسی کنید.",
  invalid_relay_worker: "نام، شناسه یا سقف ظرفیت معتبر نیست.",
  invalid_worker_origin: "نشانی پایهٔ HTTPS را وارد کنید.",
  relay_worker_exists: "این شناسه یا نشانی قبلاً در رجیستری ثبت شده است.",
  configuration_changed: "رکورد تغییر کرده است. صفحه را دوباره باز کنید و مقادیر تازه را بررسی کنید.",
  transport_endpoint_not_approved: "این نشانی در فهرست مجاز سرور نیست. راهنمای اتصال را بررسی کنید.",
  invalid_credentials: "رمز فعلی صحیح نیست.",
  relay_worker_not_verified: "ابتدا یک مسیر این Worker را از صفحهٔ ربات آزمایش کنید.",
  relay_worker_not_found: "این Worker دیگر در رجیستری موجود نیست.",
  relay_pool_disabled: "سرویس Relay خاموش است. آن را در صفحهٔ سرویس‌ها روشن کنید.",
  relay_route_not_supported: "این Worker برای ربات یا وضعیت فعلی قابل استفاده نیست.",
  relay_priority_taken: "این اولویت برای مسیر دیگری استفاده شده است.",
  relay_activation_not_ready: "برای آزمون اتصال، ابتدا توکن ربات را تأیید و کلید مسیر را ثبت کنید.",
  relay_probe_failed: "تلگرام از این مسیر پاسخ قابل تأیید نداد. نشانی Worker، نسخهٔ کلید و تنظیم Secret را بررسی کنید.",
  bot_identity_mismatch: "پاسخ تلگرام متعلق به ربات دیگری است. هش توکن و شناسهٔ ربات را در Worker بررسی کنید.",
  invalid_worker_secret: "کلید باید ۳۲ تا ۲۵۶ نویسهٔ قابل چاپ انگلیسی و بدون فاصله داشته باشد.",
  duplicate_relay_credential: "این کلید برای مسیر دیگری ثبت شده است. یک کلید مستقل وارد کنید.",
  invalid_credential_state: "وضعیت کلید تغییر کرده است. صفحه را تازه کنید.",
  bot_state_unchanged: "وضعیت انتخاب‌شده همین حالا اعمال شده است.",
  permission_denied: "حساب شما مجوز این عملیات را ندارد.",
  reauth: "برای ادامه، دوباره رمز فعلی را تأیید کنید.",
  save: "نتیجهٔ عملیات تأیید نشد. وضعیت رکورد را بررسی کنید و سپس دوباره تلاش کنید.",
};

export function relayMessage(code: string): string {
  return Object.hasOwn(relayMessages, code) ? relayMessages[code] : relayMessages.save;
}

export function relayError(error: unknown, message = false) {
  const code = error instanceof Error && "code" in error && typeof error.code === "string"
    && Object.hasOwn(relayMessages, error.code) ? error.code : "save";
  return message ? relayMessage(code) : code;
}

export function needsRelayProof(error: unknown) {
  return error instanceof Error && "code" in error && error.code === "reauthentication_required";
}

export function relayId(raw: FormDataEntryValue | null): string | null {
  return typeof raw === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(raw)
    ? raw : null;
}

export function relayInt(raw: FormDataEntryValue | null, max = 2_147_483_647): number {
  if (typeof raw !== "string" || !/^[1-9][0-9]*$/.test(raw)) return 0;
  const value = Number(raw);
  return value <= max ? value : 0;
}

export function relayPassword(raw: FormDataEntryValue | null): string | null {
  return typeof raw === "string" && raw.length > 0 && raw.length <= 256 ? raw : null;
}
