import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { controlJson } from "@/lib/control-request";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";

export const runtime = "nodejs";
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
function fail(code: string, status: number): NextResponse {
  return NextResponse.json({ ok: false, code, requestId: randomUUID() }, {
    status, headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" },
  });
}

/**
 * Public redemption requires a valid host-bound CSRF challenge. Only the
 * signed server-to-server bridge sees the submitted secret and the password.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!publicOrigin(request)) return fail("service_unavailable", 503);
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) return fail("security_check_failed", 403);
  let raw: unknown;
  try { raw = await controlJson(request, 10_240); }
  catch { return fail("invalid_request", 422); }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return fail("invalid_request", 422);
  const values = raw as Record<string, unknown>;
  if ((values.kind !== "invite" && values.kind !== "reset") ||
      typeof values.token !== "string" || !TOKEN.test(values.token) ||
      typeof values.password !== "string" || values.password.length < 12 ||
      values.password.length > 256) return fail("invalid_request", 422);
  try {
    await bridgeFetch("/auth/redeem", "POST", {
      kind: values.kind, token: values.token, password: values.password,
    }, null, 30_000);
    return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 410) return fail("invalid_link", 410);
      if (error.status === 422) return fail("password_policy_failed", 422);
      if (error.status === 429) return fail("temporarily_locked", 429);
    }
    return fail("service_unavailable", 503);
  }
}
