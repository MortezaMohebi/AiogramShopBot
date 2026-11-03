import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { createSession, sessionCookieName } from "@/lib/session";
import { trustedBrowserOrigin } from "@/lib/public-origin";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = trustedBrowserOrigin(request);
  if (!origin) {
    return new NextResponse("Forbidden", { status: 403 });
  }
  const form = await request.formData();
  const username = String(form.get("username") ?? "").trim();
  const password = String(form.get("password") ?? "");
  if (!username || username.length > 80 || password.length > 256) {
    return NextResponse.redirect(new URL("/login?error=credentials", origin), 303);
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
    return NextResponse.redirect(new URL(`/login?error=${key}`, origin), 303);
  }

  const response = NextResponse.redirect(new URL("/dashboard", origin), 303);
  response.cookies.set(sessionCookieName(), createSession(account.id, account.session_version), {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 8 * 60 * 60,
  });
  return response;
}
