import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { serverCaptchaConfig } from "@/lib/captcha-config";
import { verifyCaptchaToken } from "@/lib/captcha-verification";
import { loginChallengeCookieName, safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";
import { loginRedirect } from "@/lib/login-redirect";
import { createSession, sessionCookieName } from "@/lib/session";
import { controlJson } from "@/lib/control-request";

export const runtime = "nodejs";
interface StaffLogin { id: number; session_version: number; session_token: string; mfa_setup_required?: boolean; session_ttl_seconds?: number }
function failure(request: NextRequest, code: string, status: number, correlation?: string): NextResponse {
  const requestId = correlation && /^[a-f0-9-]{36}$/i.test(correlation) ? correlation : randomUUID();
  console.warn("[shop-admin/auth]", { requestId, code, status });
  const origin = publicOrigin(request), accept = request.headers.get("accept") ?? "";
  if (origin && accept.includes("text/html") && !accept.includes("application/json")) {
    return loginRedirect(code);
  }
  return NextResponse.json({ ok: false, code, requestId }, { status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
}
/** Password, optional CAPTCHA and optional MFA are all verified server-side. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!publicOrigin(request)) return failure(request, "service_unavailable", 503);
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) return failure(request, "security_check_failed", 403);
  let raw: unknown;
  try { raw = await controlJson(request, 10_240); }
  catch { return failure(request, "invalid_request", 422); }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return failure(request, "invalid_request", 422);
  const credentials = raw as Record<string, unknown>;
  const username = typeof credentials.username === "string" ? credentials.username.trim().toLowerCase() : "";
  const password = credentials.password, factor = credentials.second_factor ?? "";
  const rememberMe = credentials.remember_me ?? false;
  if (typeof rememberMe !== "boolean") return failure(request, "invalid_request", 422);
  if (!/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) || typeof password !== "string" || !password || password.length > 256 || typeof factor !== "string" || factor.length > 64) return failure(request, "invalid_request", 422);
  let captchaConfig;
  try { captchaConfig = serverCaptchaConfig(); } catch { return failure(request, "captcha_unavailable", 503); }
  const verdict = await verifyCaptchaToken(captchaConfig, credentials.captchaToken);
  if (verdict !== "ok") return failure(request, verdict === "required" ? "captcha_required" : verdict === "unavailable" ? "captcha_unavailable" : "captcha_failed", verdict === "unavailable" ? 503 : verdict === "required" ? 422 : 403);
  try {
    const account = await bridgeFetch<StaffLogin>("/auth/login", "POST", {
      username, password, second_factor: factor,
      ...(rememberMe ? { remember_me: true } : {}),
      device: (request.headers.get("user-agent") ?? "Browser").slice(0, 160),
    }, null);
    if (!account || !Number.isSafeInteger(account.id) || account.id < 1 || !Number.isSafeInteger(account.session_version) || account.session_version < 1 || !/^[A-Za-z0-9_-]{43}$/.test(account.session_token)) return failure(request, "service_unavailable", 503);
    const duration = rememberMe ? 30 * 24 * 60 * 60 : 8 * 60 * 60;
    // Older short-session backends remain compatible; persistence requires an
    // explicit matching backend lifetime, never just a longer browser Cookie.
    if ((rememberMe || account.session_ttl_seconds !== undefined) && account.session_ttl_seconds !== duration) return failure(request, "service_unavailable", 503);
    const response = NextResponse.json({ ok: true, redirect: account.mfa_setup_required ? "/account?enroll=1" : "/dashboard" }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(sessionCookieName(), createSession(account.id, account.session_version, account.session_token, rememberMe), { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", ...(rememberMe ? { maxAge: duration } : {}) });
    response.cookies.set(loginChallengeCookieName(), "", { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
    return response;
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 428 && error.code === "mfa_required") return failure(request, "mfa_required", 428, error.requestId);
      if (error.status === 401 && ["invalid_credentials", "invalid_verification"].includes(error.code ?? "")) return failure(request, error.code!, 401, error.requestId);
      if (error.status === 429) return failure(request, "temporarily_locked", 429, error.requestId);
      if (error.status === 503 && ["mfa_unavailable", "mfa_not_configured"].includes(error.code ?? "")) return failure(request, "mfa_unavailable", 503);
    }
    return failure(request, "service_unavailable", 503, error instanceof ApiError ? error.requestId : undefined);
  }
}
export async function GET(): Promise<NextResponse> {
  return loginRedirect();
}
