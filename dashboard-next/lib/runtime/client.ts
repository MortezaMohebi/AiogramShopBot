import { createRuntimeIntent, validRuntimeMutationReceipt, type RuntimeMutationContext } from "@/lib/runtime/receipts";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
/** Controlled errors contain only the BFF's allowlisted code and correlation ID. */
export class RuntimeError extends Error {
  constructor(readonly status: number, readonly code: string, readonly requestId?: string) {
    super(code);
    this.name = "RuntimeError";
  }
}
async function dispatch<T>(path: string, method: "GET" | "POST" = "GET", payload?: unknown, context: RuntimeMutationContext = {}): Promise<T> {
  const raw = method === "POST" ? JSON.stringify(payload ?? {}) : undefined;
  const challenge = method === "GET" ? null : await requestBrowserChallenge();
  let response: Response;
  try {
    response = await fetch(`/api/admin/workflow-runtime${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(challenge ? {
          "content-type": "application/json",
          "x-shop-login-challenge": challenge
        } : {})
      },
      body: raw,
      signal: AbortSignal.timeout(25000)
    });
  } catch {
    throw new RuntimeError(0, "network_unavailable");
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new RuntimeError(method === "POST" ? 0 : response.status, "service_unavailable");
  }
  if (!response.ok) {
    const data = value as {
      code?: string;
      requestId?: string;
    };
    throw new RuntimeError(response.status, typeof data?.code === "string" && /^[a-z][a-z0-9_]{0,80}$/.test(data.code) ? data.code : "service_unavailable", data?.requestId);
  }
  if (method === "POST" && !validRuntimeMutationReceipt(path, payload as Record<string, unknown>, value, context)) throw new RuntimeError(0, "runtime_outcome_unknown");
  return value as T;
}
/** Web Locks cover the cookie challenge and its dispatch across tabs. */
let localQueue: Promise<unknown> = Promise.resolve();
export async function runtimeRequest<T>(path: string, method: "GET" | "POST" = "GET", payload?: unknown, context: RuntimeMutationContext = {}): Promise<T> {
  if (method === "GET") return dispatch<T>(path, method, payload);
  const intent = createRuntimeIntent(path, payload, context);
  const send = () => dispatch<T>(intent.path, method, intent.payload, intent.context);
  if (typeof navigator !== "undefined" && navigator.locks) return navigator.locks.request("shop-admin-workflow-csrf", send);
  const result = localQueue.then(send, send);
  localQueue = result.then(() => undefined, () => undefined);
  return result;
}
/** Translate stable codes only; never echo raw server detail or customer input. */
export function runtimeErrorText(error: unknown): string {
  const code = error instanceof RuntimeError ? error.code : error instanceof Error ? error.message : "service_unavailable";
  const messages: Record<string, string> = {
    reauthentication_required: "هویت خود را در همین صفحه تأیید کنید. سپس وضعیت را بخوانید و درخواست تازه‌ای ثبت کنید.",
    session_expired: "نشست منقضی شده است؛ دوباره وارد شوید.",
    permission_denied: "مجوز این عملیات را در فروشگاه ندارید.",
    runtime_preview_expired: "مهلت پیش‌نمایش پایان یافته است؛ پیش‌نمایش تازه‌ای بسازید.",
    runtime_preview_conflict: "ورودی‌های فعال تغییر کرده‌اند؛ پیش‌نمایش تازه‌ای بسازید.",
    runtime_publication_not_ready: "این نسخه برای انتشار آماده نیست؛ موارد پیش‌نمایش را بررسی کنید.",
    runtime_gate_conflict: "تنظیم اجرا تغییر کرده است؛ وضعیت تازه را دریافت کنید.",
    runtime_run_conflict: "نسخهٔ اجرا تغییر کرده است؛ وضعیت تازه را دریافت کنید.",
    runtime_delivery_replay_forbidden: "ارسال دوباره برای این نتیجه مجاز نیست؛ وضعیت ارسال و رسید پیام‌رسان را بررسی کنید.",
    runtime_effect_replay_forbidden: "بازیابی این مرحله مجاز نیست؛ نتیجهٔ Action و ارسال را بررسی کنید.",
    runtime_recovery_not_applicable: "این عملیات در وضعیت فعلی اجرا قابل انجام نیست.",
    runtime_disabled: "مجوز اجرای فروشگاه یا ربات برقرار نیست.",
    runtime_entry_conflict: "این ورودی به فرایند دیگری متصل است.",
    runtime_entry_not_declared: "ورودی در نسخهٔ فرایند تعریف نشده است.",
    runtime_publication_retired: "این انتشار بازنشسته شده است و دوباره فعال نمی‌شود.",
    security_check_failed: "بررسی امنیت درخواست انجام نشد؛ صفحه را تازه کنید.",
    runtime_outcome_unknown: "پاسخ سرویس با رسید این درخواست مطابقت ندارد؛ نتیجهٔ عملیات نامعلوم است. وضعیت را بررسی کنید؛ درخواست دوباره ارسال نمی‌شود.",
    network_unavailable: "ارتباط قطع شد؛ نتیجهٔ عملیات نامعلوم است. پیش از هر اقدام وضعیت را بررسی کنید.",
    service_unavailable: "سرویس در دسترس نیست؛ نتیجهٔ عملیات هنوز تأیید نشده است."
  };
  return messages[code] ?? "عملیات تأیید نشد؛ وضعیت اجرا و مجوز فروشگاه را بررسی کنید.";
}
