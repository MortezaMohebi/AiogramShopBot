import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";

function rejected(code: string, status: number): NextResponse {
  return NextResponse.json({ ok: false, code }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Create a category inline, never bypassing editor permissions or CSRF. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return rejected("security_check_failed", 403);
  }
  const identity = await readSession();
  if (!identity) return rejected("session_expired", 401);
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return rejected("invalid_request", 415);
  }
  const announced = request.headers.get("content-length");
  if (announced && (!/^\d+$/.test(announced) || Number(announced) > 2048)) {
    return rejected("invalid_request", 413);
  }
  let payload: unknown;
  try {
    const body = await request.text();
    if (Buffer.byteLength(body, "utf8") > 2048) return rejected("invalid_request", 413);
    payload = JSON.parse(body) as unknown;
  } catch { return rejected("invalid_request", 422); }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return rejected("invalid_request", 422);
  }
  const raw = payload as Record<string, unknown>;
  const name = typeof raw.name === "string" ? raw.name.trim() : "";
  if (Object.keys(raw).some(key => key !== "name") || !name || name.length > 255) {
    return rejected("invalid_request", 422);
  }
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, identity);
    if (!["superadmin", "content"].includes(staff.role)) {
      return rejected("permission_denied", 403);
    }
    const created = await bridgeFetch<{ id: number }>(
      "/categories", "POST", { name, is_published: false }, identity,
    );
    return NextResponse.json({ ok: true, id: created.id, name }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return rejected("session_expired", 401);
      if (error.status === 403) return rejected("permission_denied", 403);
      if (error.status === 409) return rejected("already_exists", 409);
      if (error.status === 422) return rejected("invalid_request", 422);
    }
    return rejected("service_unavailable", 503);
  }
}
