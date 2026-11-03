import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import {
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { ShopSettings, Staff } from "@/lib/types";

export const runtime = "nodejs";
// Match the signed FastAPI JSON ceiling. The form permits up to 24,851
// Unicode characters, which can exceed 30 KB in UTF-8 or escaped JSON.
const MAX_BODY_BYTES = 256 * 1024;

/** Distinguish a body limit from ordinary invalid field content. */
class SettingsBodyTooLarge extends Error {}

type FailureCode =
  | "invalid_request"
  | "security_check_failed"
  | "session_expired"
  | "permission_denied"
  | "service_unavailable"
  | "save_failed";

function failure(code: FailureCode, status: number): NextResponse {
  /** Return an opaque request ID, without exposing tokens or backend errors. */
  const requestId = randomUUID();
  console.warn("[shop-admin/settings]", { requestId, code, status });
  return NextResponse.json(
    { ok: false, code, requestId },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}

/** Refuse oversized bodies even if an intermediary omits Content-Length. */
async function boundedJson(request: NextRequest): Promise<unknown> {
  const announced = request.headers.get("content-length");
  if (announced && !/^\d+$/.test(announced)) {
    throw new Error("invalid_request");
  }
  if (announced && Number(announced) > MAX_BODY_BYTES) {
    await request.body?.cancel().catch(() => undefined);
    throw new SettingsBodyTooLarge();
  }
  if (!request.body) throw new Error("invalid_request");

  const reader = request.body.getReader();
  const parts: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) throw new SettingsBodyTooLarge();
      parts.push(value);
    }
  } catch (error) {
    // Stop reading a rejected upload rather than leaving its stream active.
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }

  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(
      Buffer.concat(parts),
    );
    return JSON.parse(decoded) as unknown;
  } catch {
    throw new Error("invalid_request");
  }
}

/** Allowlist merchant-facing copy only; never accept secrets or modes. */
function validatePayload(payload: unknown): ShopSettings | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const raw = payload as Record<string, unknown>;
  const permitted = [
    "brand_name", "welcome_message", "faq_text", "support_url",
  ] as const;
  if (Object.keys(raw).some((key) => !permitted.includes(key as typeof permitted[number]))) {
    return null;
  }
  if (permitted.some((key) => typeof raw[key] !== "string")) {
    return null;
  }
  const data = Object.fromEntries(
    permitted.map((key) => [key, (raw[key] as string).trim()]),
  ) as unknown as ShopSettings;

  if (
    data.brand_name.length > 255 ||
    data.welcome_message.length > 4096 ||
    data.faq_text.length > 20_000 ||
    data.support_url.length > 500
  ) {
    return null;
  }
  if (data.support_url) {
    try {
      const url = new URL(data.support_url);
      if (
        url.protocol !== "https:" ||
        url.username || url.password ||
        url.hostname.length === 0
      ) {
        return null;
      }
    } catch {
      return null;
    }
  }
  return data;
}

/** Signed BFF write, using the same FastAPI/SQLAlchemy session as all bots. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (
    !safeLoginFetchMetadata(request) ||
    !verifyLoginChallenge(request)
  ) return failure("security_check_failed", 403);

  const session = await readSession();
  if (!session) return failure("session_expired", 401);
  const contentType = (request.headers.get("content-type") ?? "")
    .split(";", 1)[0].trim().toLowerCase();
  if (contentType !== "application/json") {
    return failure("invalid_request", 415);
  }

  let payload: unknown;
  try {
    payload = await boundedJson(request);
  } catch (error) {
    return failure("invalid_request", error instanceof SettingsBodyTooLarge ? 413 : 422);
  }
  const data = validatePayload(payload);
  if (!data) return failure("invalid_request", 422);

  let writeAccepted = false;
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (staff.role !== "superadmin") {
      return failure("permission_denied", 403);
    }
    await bridgeFetch("/settings", "PATCH", data, session);
    writeAccepted = true;
    const saved = await bridgeFetch<ShopSettings>(
      "/settings", "GET", null, session,
    );
    // Report success only if the database-backed read reflects the write.
    if (
      Object.keys(data).some(
        (key) => saved[key as keyof ShopSettings] !==
          data[key as keyof ShopSettings],
      )
    ) {
      return failure("save_failed", 503);
    }
    return NextResponse.json(
      { ok: true, settings: saved },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    // A failed verification after PATCH is not proof that the write failed.
    // Do not invite a blind retry or falsely report a confirmed save.
    if (writeAccepted) return failure("save_failed", 503);
    if (error instanceof ApiError) {
      if (error.status === 401) return failure("session_expired", 401);
      if (error.status === 403) return failure("permission_denied", 403);
      if (error.status === 422) return failure("invalid_request", 422);
    }
    return failure("service_unavailable", 503);
  }
}
