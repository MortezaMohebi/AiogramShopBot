import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import {
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";

/** Stage a mode change, but never switch a live Bot API receiver in an HTTP POST. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return NextResponse.json(
      { ok: false, code: "security_check_failed" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  const session = await readSession();
  if (!session) {
    return NextResponse.json(
      { ok: false, code: "session_expired" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }
  if ((request.headers.get("content-type") ?? "").split(";")[0] !== "application/json") {
    return NextResponse.json(
      { ok: false, code: "invalid_request" },
      { status: 415, headers: { "Cache-Control": "no-store" } },
    );
  }
  const length = request.headers.get("content-length");
  if (length && (!/^\d+$/.test(length) || Number(length) > 512)) {
    return NextResponse.json(
      { ok: false, code: "invalid_request" },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }

  let payload: unknown;
  try {
    const bytes = await request.text();
    if (bytes.length > 512) throw new Error("too long");
    payload = JSON.parse(bytes) as unknown;
  } catch {
    return NextResponse.json(
      { ok: false, code: "invalid_request" },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }
  const candidate = payload as {mode?: unknown; confirmation?: unknown} | null;
  if (
    !candidate ||
    (candidate.mode !== "polling" && candidate.mode !== "webhook") ||
    candidate.confirmation !== "STAGE_TELEGRAM_MODE"
  ) {
    return NextResponse.json(
      { ok: false, code: "invalid_request" },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (staff.role !== "superadmin") {
      return NextResponse.json(
        { ok: false, code: "permission_denied" },
        { status: 403, headers: { "Cache-Control": "no-store" } },
      );
    }
    const result = await bridgeFetch<{
      ok: boolean;
      pending_update_mode: string;
      activation: string;
    }>("/bot-connections/telegram-mode-request", "POST", candidate, session);

    return NextResponse.json(result, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const code = error instanceof ApiError && error.status === 401
      ? "session_expired"
      : error instanceof ApiError && error.status === 403
        ? "permission_denied"
        : "service_unavailable";
    return NextResponse.json(
      { ok: false, code },
      { status: code === "session_expired" ? 401
        : code === "permission_denied" ? 403 : 503,
        headers: { "Cache-Control": "no-store" } },
    );
  }
}
