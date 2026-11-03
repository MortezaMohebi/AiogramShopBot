import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { loginChallengeCookieName, safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";
import { readSession, sessionCookieName } from "@/lib/session";
export const runtime = "nodejs";
/** Revoke the server session before telling the browser that logout succeeded. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return NextResponse.json({ ok: false, code: "security_check_failed" }, { status: 403, headers: { "Cache-Control": "no-store" } });
  }
  const session = await readSession();
  if (session) {
    try { await bridgeFetch("/auth/logout", "POST", {}, session); }
    catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) return NextResponse.json({ ok: false, code: "service_unavailable" }, { status: 503, headers: { "Cache-Control": "no-store" } });
    }
  }
  const response = NextResponse.json({ ok: true, redirect: "/login" }, { headers: { "Cache-Control": "no-store" } });
  for (const name of [sessionCookieName(), loginChallengeCookieName()]) response.cookies.set(name, "", { httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 0 });
  return response;
}
export async function GET(request: NextRequest): Promise<NextResponse> {
  return NextResponse.redirect(new URL("/login", publicOrigin(request) ?? request.url), 303);
}
