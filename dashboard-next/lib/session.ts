import "server-only";

import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

interface SessionClaims {
  /** Backend staff primary key; role is ALWAYS revalidated by FastAPI. */
  id: number;
  version: number;
  expires: number;
}

/** Use host-only cookies with Secure mode in production HTTPS. */
export function sessionCookieName(): string {
  return process.env.NODE_ENV === "production"
    ? "__Host-shop_admin"
    : "shop_admin_dev";
}

function secret(): string {
  const key = process.env.NEXT_ADMIN_SESSION_SECRET ?? "";
  if (key.length < 32) {
    throw new Error("NEXT_ADMIN_SESSION_SECRET must contain 32+ characters.");
  }
  return key;
}

function signature(payload: string): Buffer {
  return createHmac("sha256", secret()).update(payload).digest();
}

/** Sign a short-lived opaque-to-the-browser identity reference, not a role. */
export function createSession(id: number, version: number): string {
  if (!Number.isSafeInteger(id) || id < 1 || !Number.isSafeInteger(version)) {
    throw new Error("Invalid administrator session.");
  }
  const claims: SessionClaims = {
    id,
    version,
    expires: Math.floor(Date.now() / 1000) + 8 * 60 * 60,
  };
  const payload = Buffer.from(JSON.stringify(claims)).toString("base64url");
  return `${payload}.${signature(payload).toString("base64url")}`;
}

/** Reject malformed, tampered or expired sessions before backend lookup. */
export function verifySession(token?: string): SessionClaims | null {
  if (!token || token.length > 1024) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  try {
    const [payload, mac] = parts;
    const actual = Buffer.from(mac, "base64url");
    const expected = signature(payload);
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) {
      return null;
    }
    const claims: unknown = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    );
    if (
      typeof claims !== "object" ||
      claims === null ||
      !("id" in claims) ||
      !("version" in claims) ||
      !("expires" in claims)
    ) {
      return null;
    }
    const data = claims as SessionClaims;
    if (
      !Number.isSafeInteger(data.id) || data.id < 1 ||
      !Number.isSafeInteger(data.version) || data.version < 1 ||
      !Number.isSafeInteger(data.expires) ||
      data.expires <= Math.floor(Date.now() / 1000)
    ) {
      return null;
    }
    return data;
  } catch {
    return null;
  }
}

/** Server-only read; no long-lived browser credential reaches the API. */
export async function readSession(): Promise<SessionClaims | null> {
  const cookie = (await cookies()).get(sessionCookieName());
  return verifySession(cookie?.value);
}
