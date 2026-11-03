import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import {
  loginChallengeCookieName,
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
import { type LoginErrorCode } from "@/lib/login-errors";
import { publicOrigin } from "@/lib/public-origin";
import { createSession, sessionCookieName } from "@/lib/session";

export const runtime = "nodejs";
const MAX_LOGIN_BODY_BYTES = 4096;

interface StaffLogin {
  id: number;
  username: string;
  session_version: number;
}

/** Use a configured origin for safe redirects, not a proxy-derived Host. */
function isHtmlNavigation(request: NextRequest): boolean {
  const accept = request.headers.get("accept") ?? "";
  return accept.includes("text/html") && !accept.includes("application/json");
}

/** Always return a structured error, or a safe legacy-form redirect. */
function failure(
  request: NextRequest,
  code: LoginErrorCode,
  status: number,
): NextResponse {
  const requestId = randomUUID();
  const origin = publicOrigin(request);

  // Existing browser tabs might still submit the old native HTML form.
  // Keep them out of a raw Forbidden response; tell them to reload login.
  if (isHtmlNavigation(request) && origin) {
    const target = new URL("/login", origin);
    target.searchParams.set("error", code);
    return NextResponse.redirect(target, 303);
  }

  return NextResponse.json(
    { ok: false, code, requestId },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-Request-ID": requestId,
      },
    },
  );
}

/** Enforce a small body limit even when Content-Length is absent. */
async function boundedLoginJson(request: NextRequest): Promise<unknown> {
  const length = request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length) > MAX_LOGIN_BODY_BYTES)) {
    throw new Error("invalid_request");
  }
  if (!request.body) {
    throw new Error("invalid_request");
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_LOGIN_BODY_BYTES) {
        await reader.cancel();
        throw new Error("invalid_request");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  try {
    const text = Buffer.concat(chunks).toString("utf8");
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error("invalid_request");
  }
}

/** Perform authentication only after a verified, host-bound CSRF challenge. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = publicOrigin(request);
  if (!origin) return failure(request, "service_unavailable", 503);

  // Codespaces may change/drop Origin; never disable CSRF to compensate.
  // Same-origin JS proves intent with an unpredictable HttpOnly cookie pair.
  if (
    !safeLoginFetchMetadata(request) ||
    !verifyLoginChallenge(request)
  ) {
    return failure(request, "security_check_failed", 403);
  }

  // Reject a demonstrably foreign Origin unless browser Fetch Metadata
  // confirms same-origin intent. A proxy-stripped Origin is acceptable only
  // because the random, host-only double-submit challenge is verified.
  const headerOrigin = request.headers.get("origin");
  if (
    headerOrigin &&
    headerOrigin !== "null" &&
    headerOrigin !== origin.origin &&
    request.headers.get("sec-fetch-site") !== "same-origin"
  ) {
    return failure(request, "security_check_failed", 403);
  }

  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return failure(request, "invalid_request", 415);
  }

  let payload: unknown;
  try {
    payload = await boundedLoginJson(request);
  } catch {
    return failure(request, "invalid_request", 422);
  }

  if (!payload || typeof payload !== "object") {
    return failure(request, "invalid_request", 422);
  }

  const credentials = payload as Record<string, unknown>;
  const username = typeof credentials.username === "string"
    ? credentials.username.trim().toLowerCase()
    : "";
  const password = credentials.password;
  if (
    !/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) ||
    typeof password !== "string" ||
    password.length < 1 ||
    password.length > 256
  ) {
    return failure(request, "invalid_request", 422);
  }

  let account: StaffLogin;
  try {
    account = await bridgeFetch<StaffLogin>(
      "/auth/login", "POST", { username, password }, null,
    );
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) {
        return failure(request, "invalid_credentials", 401);
      }
      if (error.status === 429) {
        return failure(request, "temporarily_locked", 429);
      }
    }
    // Do not reveal internal endpoints, provider tokens or authentication
    // exception messages in a browser response.
    return failure(request, "service_unavailable", 503);
  }

  if (
    !Number.isSafeInteger(account.id) ||
    account.id < 1 ||
    !Number.isSafeInteger(account.session_version) ||
    account.session_version < 1
  ) {
    return failure(request, "service_unavailable", 503);
  }

  const response = NextResponse.json(
    { ok: true, redirect: "/dashboard" },
    { headers: { "Cache-Control": "no-store" } },
  );
  response.cookies.set(
    sessionCookieName(),
    createSession(account.id, account.session_version),
    {
      httpOnly: true,
      sameSite: "strict",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 8 * 60 * 60,
    },
  );
  response.cookies.set(loginChallengeCookieName(), "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return response;
}

/** An opened API URL goes back to the login page, never a raw 405 screen. */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const target = new URL(
    "/login",
    publicOrigin(request) ?? request.url,
  );
  return NextResponse.redirect(target, 303);
}
