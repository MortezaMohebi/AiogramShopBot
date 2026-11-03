import { NextResponse, type NextRequest } from "next/server";
import {
  issueLoginChallenge,
  loginChallengeCookieName,
  loginChallengeMaxAge,
  safeLoginFetchMetadata,
} from "@/lib/login-challenge";
import { publicOrigin } from "@/lib/public-origin";

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

  const challenge = issueLoginChallenge();
  const response = NextResponse.json(
    { ok: true, challenge },
    { headers: { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } },
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
