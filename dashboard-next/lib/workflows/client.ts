import { requestBrowserChallenge } from "@/lib/browser-challenge";
/** Controlled errors contain only the BFF's allowlisted code and correlation ID. */
export class WorkflowError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly requestId?: string,
  ) {
    super(code);
    this.name = "WorkflowError";
  }
}
async function dispatch<T>(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
  payload?: unknown,
): Promise<T> {
  const challenge = method === "GET" ? null : await requestBrowserChallenge();
  let response: Response;
  try {
    response = await fetch(`/api/admin/workflows${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(challenge
          ? {
              "content-type": "application/json",
              "x-shop-login-challenge": challenge,
            }
          : {}),
      },
      body: method === "GET" ? undefined : JSON.stringify(payload ?? {}),
      signal: AbortSignal.timeout(25000),
    });
  } catch {
    throw new WorkflowError(0, "network_unavailable");
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new WorkflowError(response.status, "service_unavailable");
  }
  if (!response.ok) {
    const data = value as { code?: string; requestId?: string };
    throw new WorkflowError(
      response.status,
      data?.code ?? "service_unavailable",
      data?.requestId,
    );
  }
  return value as T;
}
/** Web Locks cover the cookie challenge and its dispatch across tabs. */
let localQueue: Promise<unknown> = Promise.resolve();
export async function workflowRequest<T>(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
  payload?: unknown,
): Promise<T> {
  if (method === "GET") return dispatch<T>(path, method, payload);
  const send = () => dispatch<T>(path, method, payload);
  if (typeof navigator !== "undefined" && navigator.locks)
    return navigator.locks.request("shop-admin-workflow-csrf", send);
  const result = localQueue.then(send, send);
  localQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}
const messages: Record<string, string> = {
  workflow_revision_conflict:
    "نسخهٔ سرور تغییر کرده است. ویرایش محلی حفظ شد؛ نسخه‌ها را مقایسه کنید.",
  workflow_operation_conflict:
    "شناسهٔ عملیات قبلاً با دادهٔ دیگری استفاده شده است.",
  workflow_invalid_request: "ساختار یا مقدار یکی از فیلدها معتبر نیست.",
  workflow_key_exists: "این کلید در فروشگاه استفاده شده است.",
  workflow_bot_not_available:
    "ربات انتخاب‌شده برای این فروشگاه یا پلتفرم در دسترس نیست.",
  workflow_media_not_available:
    "رسانهٔ انتخاب‌شده در این فروشگاه در دسترس نیست.",
  workflow_runtime_unavailable:
    "فعال‌سازی پس از پیاده‌سازی و بررسی Runtime فراهم می‌شود.",
  permission_denied: "مجوز این عملیات را ندارید.",
  session_expired: "نشست شما منقضی شده است؛ دوباره وارد شوید.",
  security_check_failed: "بررسی امنیت درخواست انجام نشد؛ صفحه را تازه کنید.",
  network_unavailable: "ارتباط قطع شد؛ نتیجهٔ عملیات هنوز تأیید نشده است.",
  service_unavailable:
    "سرویس در دسترس نیست؛ نتیجهٔ عملیات هنوز تأیید نشده است.",
};
export function errorText(error: unknown): string {
  return error instanceof WorkflowError
    ? `${messages[error.code] ?? "عملیات تأیید نشد. دادهٔ محلی حفظ شده است."}${error.requestId ? ` (${error.requestId})` : ""}`
    : error instanceof Error && messages[error.message]
      ? messages[error.message]
      : "عملیات تأیید نشد؛ دوباره وضعیت را بررسی کنید.";
}
