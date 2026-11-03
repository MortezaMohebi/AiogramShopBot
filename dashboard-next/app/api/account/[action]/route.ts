import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession, sessionCookieName } from "@/lib/session";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { controlJson } from "@/lib/control-request";
export const runtime = "nodejs";
type Context = { params: Promise<{ action: string }> };
const READS: Record<string, string> = { summary: "/account", permissions: "/account/permissions", connections: "/connection-changes" };
const WRITES: Record<string, string> = {
  profile: "/account/profile", password: "/account/password", reauthenticate: "/account/reauthenticate",
  preferences: "/account/preferences", username: "/account/username",
  "revoke-session": "/account/revoke-session", "revoke-others": "/account/revoke-others",
  "mfa-setup": "/account/mfa-setup", "mfa-confirm": "/account/mfa-confirm", "mfa-disable": "/account/mfa-disable",
  "connection-stage": "/connection-changes", "connection-action": "/connection-changes/action",
  "staff-invite": "/staff/invitations", "staff-invite-cancel": "/staff/invitations/cancel",
  "staff-reset": "/staff/password-reset", "password-policy": "/staff/password-policy",
};
function fail(code: string, status: number): NextResponse {
  return NextResponse.json({ ok: false, code, requestId: randomUUID() }, { status, headers: { "Cache-Control": "no-store" } });
}
/** Fixed path map: no generic admin proxy or client-selectable backend URL. */
async function handle(request: NextRequest, context: Context, write: boolean): Promise<NextResponse> {
  const { action } = await context.params, map = write ? WRITES : READS;
  if (!Object.hasOwn(map, action)) return fail("not_found", 404);
  const session = await readSession(); if (!session) return fail("session_expired", 401);
  let data: unknown = null;
  if (write) {
    if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) return fail("security_check_failed", 403);
    try { data = await controlJson(request); } catch { return fail("invalid_request", 422); }
  }
  try {
    const result = await bridgeFetch<Record<string, unknown>>(map[action], write ? "POST" : "GET", data, session);
    const response = NextResponse.json(result, { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
    if (result.login_required === true) response.cookies.set(sessionCookieName(), "", { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
    return response;
  } catch (error) {
    return error instanceof ApiError ? fail(error.code ?? (error.status === 401 ? "session_expired" : "service_unavailable"), error.status) : fail("service_unavailable", 503);
  }
}
export function GET(request: NextRequest, context: Context) { return handle(request, context, false); }
export function POST(request: NextRequest, context: Context) { return handle(request, context, true); }
