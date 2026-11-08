import { NextResponse, type NextRequest } from "next/server";
import {
  issueLoginChallenge,
  issueSessionChallenge,
  isLoginChallenge,
  loginChallengeCookieName,
  loginChallengeMaxAge,
  safeLoginFetchMetadata,
} from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Set a random HttpOnly SameSite cookie and deliver its matching token only
 * to same-origin JavaScript. Cross-origin sites cannot read this JSON.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  if (!publicOrigin(request)) {
    return NextResponse.json(
      { ok: false, code: "service_unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  if (!safeLoginFetchMetadata(request)) {
    return NextResponse.json(
      { ok: false, code: "security_check_failed" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  const session = await readSession();
  const existing = request.cookies.get(loginChallengeCookieName())?.value;
  // A session-specific MAC is unpredictable and identical for simultaneous
  // first requests. Cookie expiry refreshes its lifetime without invalidating
  // another tab's in-flight mutation. All origin/cookie checks remain intact.
  const challenge = session
    ? issueSessionChallenge(session)
    : isLoginChallenge(existing)
      ? existing
      : issueLoginChallenge();
  const response = NextResponse.json(
    { ok: true, challenge },
    {
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
  response.cookies.set(loginChallengeCookieName(), challenge, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict",
    path: "/",
    maxAge: loginChallengeMaxAge,
  });
  return response;
}
