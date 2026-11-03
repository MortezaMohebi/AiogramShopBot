import "server-only";
import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";

export interface SessionClaims {
  id: number;
  version: number;
  expires: number;
  /** Opaque backend-issued token; never exposed to client components. */
  sid: string;
}
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
export function sessionCookieName(): string {
  return process.env.NODE_ENV === "production" ? "__Host-shop_admin" : "shop_admin_dev";
}
function signature(payload: string): Buffer {
  const key = process.env.NEXT_ADMIN_SESSION_SECRET ?? "";
  if (key.length < 32) throw new Error("Session signing key is missing");
  return createHmac("sha256", key).update(payload).digest();
}
/** Keep the signed browser envelope bound to a revocable backend session. */
export function createSession(id: number, version: number, sid: string): string {
  if (!Number.isSafeInteger(id) || id < 1 || !Number.isSafeInteger(version) || version < 1 || !TOKEN.test(sid)) {
    throw new Error("Invalid administrator session");
  }
  const claims: SessionClaims = { id, version, sid, expires: Math.floor(Date.now() / 1000) + 8 * 60 * 60 };
  const payload = Buffer.from(JSON.stringify(claims)).toString("base64url");
  return `${payload}.${signature(payload).toString("base64url")}`;
}
/** Old password-only cookies require login again after the security upgrade. */
export function verifySession(token?: string): SessionClaims | null {
  if (!token || token.length > 1024) return null;
  try {
    const parts = token.split(".");
    if (parts.length !== 2) return null;
    const [payload, mac] = parts;
    const actual = Buffer.from(mac, "base64url"), expected = signature(payload);
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected)) return null;
    const data = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Partial<SessionClaims>;
    if (!data || !Number.isSafeInteger(data.id) || (data.id ?? 0) < 1 ||
        !Number.isSafeInteger(data.version) || (data.version ?? 0) < 1 ||
        !Number.isSafeInteger(data.expires) || (data.expires ?? 0) <= Math.floor(Date.now() / 1000) ||
        typeof data.sid !== "string" || !TOKEN.test(data.sid)) return null;
    return data as SessionClaims;
  } catch { return null; }
}
export async function readSession(): Promise<SessionClaims | null> {
  return verifySession((await cookies()).get(sessionCookieName())?.value);
}
