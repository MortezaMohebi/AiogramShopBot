import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";
const MAX_BYTES = 120_000;
const keys = new Set([
  "sku", "external_ref", "uom_id", "purchase_uom_id",
  "name", "description", "category_id", "price_irr",
  "price_stars", "stock_quantity", "product_type", "requires_shipping",
  "is_published", "show_description", "show_stock", "show_media", "show_reviews",
]);

function failed(code: string, status: number): NextResponse {
  const requestId = randomUUID();
  console.warn("[shop-admin/product-save]", { code, status, requestId });
  return NextResponse.json({ ok: false, code, requestId }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Save real products through the signed bridge, not a native Server Action. */
async function save(request: NextRequest, method: "POST" | "PATCH") {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return failed("security_check_failed", 403);
  }
  const session = await readSession();
  if (!session) return failed("session_expired", 401);
  if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
    return failed("invalid_request", 415);
  }
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES)) {
    return failed("invalid_request", 413);
  }
  let raw: unknown;
  try {
    const body = await request.text();
    if (Buffer.byteLength(body, "utf8") > MAX_BYTES) return failed("invalid_request", 413);
    raw = JSON.parse(body) as unknown;
  } catch { return failed("invalid_request", 422); }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return failed("invalid_request", 422);
  }
  const source = raw as Record<string, unknown>;
  const id = source.id;
  const values = Object.fromEntries(Object.entries(source).filter(([key]) => key !== "id"));
  if (Object.keys(values).some(key => !keys.has(key))) return failed("invalid_request", 422);
  if (method === "PATCH" && (!Number.isSafeInteger(id) || (id as number) <= 0)) {
    return failed("invalid_request", 422);
  }
  if (method === "POST" && id !== undefined) return failed("invalid_request", 422);
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (!["superadmin", "content"].includes(staff.role)) {
      return failed("permission_denied", 403);
    }
    const saved = await bridgeFetch<{ id: number }>(
      method === "POST" ? "/products" : "/products/" + String(id),
      method, values, session,
    );
    return NextResponse.json({ ok: true, id: saved.id }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return failed("session_expired", 401);
      if (error.status === 403) return failed("permission_denied", 403);
      if (error.status === 404) return failed("not_found", 404);
      if (error.status === 409) return failed("sku_exists", 409);
      if (error.status === 422) return failed("invalid_product", 422);
    }
    return failed("service_unavailable", 503);
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  return save(request, "POST");
}

export async function PATCH(request: NextRequest): Promise<NextResponse> {
  return save(request, "PATCH");
}
