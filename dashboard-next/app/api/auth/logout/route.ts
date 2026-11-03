import { NextResponse, type NextRequest } from "next/server";
import {
  loginChallengeCookieName,
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";
import { sessionCookieName } from "@/lib/session";

export const runtime = "nodejs";

/** Keep obsolete native forms out of a raw Forbidden page. */
function securityError(request: NextRequest): NextResponse {
  const origin = publicOrigin(request);
  const accept = request.headers.get("accept") ?? "";
  if (origin && accept.includes("text/html") && !accept.includes("application/json")) {
    return NextResponse.redirect(
      new URL("/login?error=security_check_failed", origin),
      303,
    );
  }
  return NextResponse.json(
    { ok: false, code: "security_check_failed" },
    { status: 403, headers: { "Cache-Control": "no-store" } },
  );
}

/** Invalidate the host-only session after verifying same-origin intent. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const expected = publicOrigin(request);
  if (!expected) {
    return NextResponse.json(
      { ok: false, code: "service_unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return securityError(request);
  }

  const origin = request.headers.get("origin");
  if (
    origin &&
    origin !== "null" &&
    origin !== expected.origin &&
    request.headers.get("sec-fetch-site") !== "same-origin"
  ) {
    return securityError(request);
  }

  const response = NextResponse.json(
    { ok: true, redirect: "/login" },
    { headers: { "Cache-Control": "no-store" } },
  );

  // Host-only, Secure in production; do not rely on browser-side clearing.
  response.cookies.set(sessionCookieName(), "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  response.cookies.set(loginChallengeCookieName(), "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return response;
}

/** Show the login screen when users open the endpoint in the address bar. */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return NextResponse.redirect(
    new URL("/login", publicOrigin(request) ?? request.url),
    303,
  );
}
