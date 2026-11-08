import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { controlJson } from "@/lib/control-request";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";

type Entity = "products" | "categories";
const MAX_BYTES = 40_000;

function failed(code: string, status: number) {
  const requestId = randomUUID();
  console.warn("[shop-admin/bulk-unpublish]", { code, status, requestId });
  return NextResponse.json({ ok: false, code, requestId }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Unpublish a bounded selection via one signed, store-scoped transaction. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return failed("security_check_failed", 403);
  }
  const identity = await readSession();
  if (!identity) return failed("session_expired", 401);
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return failed("invalid_request", 415);
  }
  const announced = request.headers.get("content-length");
  if (announced && (!/^\d+$/.test(announced) || Number(announced) > MAX_BYTES)) {
    return failed("invalid_request", 413);
  }
  let raw: unknown;
  try { raw = await controlJson(request, MAX_BYTES); }
  catch { return failed("invalid_request", 422); }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return failed("invalid_request", 422);
  }
  const value = raw as Record<string, unknown>;
  const entity = value.entity;
  const ids = value.ids;
  if ((entity !== "products" && entity !== "categories") ||
    Object.keys(value).some((key) => key !== "entity" && key !== "ids") ||
    !Array.isArray(ids) || ids.length < 1 || ids.length > 2000 ||
    ids.some((id) => !Number.isSafeInteger(id) || id <= 0) ||
    new Set(ids).size !== ids.length) {
    return failed("invalid_request", 422);
  }
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, identity);
    if (!["superadmin", "content"].includes(staff.role)) {
      return failed("permission_denied", 403);
    }
    const result = await bridgeFetch<{ selected: number; unpublished: number }>(
      `/${entity as Entity}/bulk-unpublish`, "POST", { ids }, identity,
    );
    return NextResponse.json({ ok: true, ...result }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return failed("session_expired", 401);
      if (error.status === 403) return failed("permission_denied", 403);
      if (error.status === 404) return failed("selection_changed", 404);
      if (error.status === 422) return failed("invalid_request", 422);
    }
    return failed("service_unavailable", 503);
  }
}
