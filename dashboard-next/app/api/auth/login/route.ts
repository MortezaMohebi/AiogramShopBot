import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { createSession, sessionCookieName } from "@/lib/session";

/** Refuse cross-origin login forms even if a browser sends stored cookies. */
function trustedOrigin(request: NextRequest): boolean {
  return request.headers.get("origin") === request.nextUrl.origin;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!trustedOrigin(request)) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const form = await request.formData();
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!username || username.length > 80 || password.length > 256) {
    return NextResponse.redirect(new URL("/login?error=credentials", request.url), 303);
  }

  let account: {id: number; username: string; session_version: number};
  try {
    account = await bridgeFetch(
      "/auth/login", "POST", { username, password }, null,
    );
  } catch (error) {
    const key =
      error instanceof ApiError && error.status === 429
        ? "locked"
        : error instanceof ApiError && error.status === 503
          ? "unavailable"
          : "credentials";
    return NextResponse.redirect(new URL(`/login?error=${key}`, request.url), 303);
  }

  const response = NextResponse.redirect(new URL("/dashboard", request.url), 303);
  response.cookies.set(sessionCookieName(), createSession(account.id, account.session_version), {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 8 * 60 * 60,
  });
  return response;
}
