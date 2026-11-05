import { requestBrowserChallenge } from "@/lib/browser-challenge";
/** Controlled failure from the existing signed/CSRF boundary. */
export class ActionRequestError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
  ) {
    super(code);
  }
}
/** This client can only reach the closed Action BFF; no live execute route exists. */
export async function actionRequest<T>(
  path: string,
  method: "GET" | "POST" = "GET",
  input?: unknown,
): Promise<T> {
  const challenge = method === "POST" ? await requestBrowserChallenge() : null;
  let response: Response;
  try {
    response = await fetch(`/api/admin/actions${path}`, {
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
      body: method === "POST" ? JSON.stringify(input ?? {}) : undefined,
      signal: AbortSignal.timeout(25000),
    });
  } catch {
    throw new ActionRequestError("service_unavailable", 0);
  }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok || data === null) {
    const code =
      (data as { code?: unknown; detail?: unknown } | null)?.code ??
      (data as { detail?: unknown } | null)?.detail;
    throw new ActionRequestError(
      typeof code === "string" && /^[a-z][a-z0-9_]{0,80}$/.test(code)
        ? code
        : "service_unavailable",
      response.status,
    );
  }
  return data as T;
}
