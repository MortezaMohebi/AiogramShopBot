import "server-only";

import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import type { NextRequest } from "next/server";
import type { SessionClaims } from "@/lib/session";

const CHALLENGE_BYTES = 32;
const CHALLENGE_LIFETIME_SECONDS = 600;
const TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;

/** Host-only cookie: sibling domains cannot overwrite the security token. */
export function loginChallengeCookieName(): string {
  return process.env.NODE_ENV === "production"
    ? "__Host-shop_login_challenge"
    : "shop_login_challenge_dev";
}

/** The challenge is issued on a same-origin GET before every login attempt. */
export function issueLoginChallenge(): string {
  return randomBytes(CHALLENGE_BYTES).toString("base64url");
}

/** Keep authenticated CSRF stable across tabs, including the first request. */
export function issueSessionChallenge(session: SessionClaims): string {
  const key = process.env.NEXT_ADMIN_SESSION_SECRET ?? "";
  if (key.length < 32) throw new Error("Session signing key is missing");
  return createHmac("sha256", key)
    .update(
      ["shop-admin-csrf-v1", session.id, session.version, session.sid].join(
        "\n",
      ),
    )
    .digest("base64url");
}

/** Only an existing correctly shaped host cookie can be reused before login. */
export function isLoginChallenge(value: unknown): value is string {
  return typeof value === "string" && TOKEN_PATTERN.test(value);
}

export const loginChallengeMaxAge = CHALLENGE_LIFETIME_SECONDS;

/** Constant-time double-submit validation independent of forwarded Origin. */
export function verifyLoginChallenge(request: NextRequest): boolean {
  const submitted = request.headers.get("x-shop-login-challenge") ?? "";
  const cookie = request.cookies.get(loginChallengeCookieName())?.value ?? "";

  if (!TOKEN_PATTERN.test(submitted) || !TOKEN_PATTERN.test(cookie)) {
    return false;
  }
  const submittedBytes = Buffer.from(submitted, "ascii");
  const cookieBytes = Buffer.from(cookie, "ascii");
  return (
    submittedBytes.length === cookieBytes.length &&
    timingSafeEqual(submittedBytes, cookieBytes)
  );
}

/**
 * Reject cross-site browser requests. The unpredictable host-bound
 * challenge provides CSRF protection even if Codespaces strips Origin.
 *
 * Browser Fetch Metadata is an additional defense, not the only one.
 */
export function safeLoginFetchMetadata(request: NextRequest): boolean {
  const site = request.headers.get("sec-fetch-site");
  return (
    site === null ||
    site === "same-origin" ||
    site === "same-site" ||
    site === "none"
  );
}
