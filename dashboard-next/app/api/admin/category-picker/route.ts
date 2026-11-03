import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import { controlJson } from "@/lib/control-request";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";

export const runtime = "nodejs";

function error(code: string, status: number): NextResponse {
  return NextResponse.json({ ok: false, code }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Read current options and never trust a client-supplied backend path. */
export async function GET(): Promise<NextResponse> {
  const session = await readSession();
  if (!session) return error("session_expired", 401);
  try {
    const result = await bridgeFetch("/categories", "GET", null, session);
    return NextResponse.json({ ok: true, items: result }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (failure) {
    if (failure instanceof ApiError) return error(failure.code ?? "service_unavailable", failure.status);
    return error("service_unavailable", 503);
  }
}

/** Inline create/edit uses the same FastAPI RBAC and validation as category pages. */
async function mutate(request: NextRequest, method: "POST" | "PATCH"): Promise<NextResponse> {
  const session = await readSession();
  if (!session) return error("session_expired", 401);
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) return error("security_check_failed", 403);
  let value: unknown;
  try { value = await controlJson(request, 4096); }
  catch { return error("invalid_request", 422); }
  if (!value || typeof value !== "object" || Array.isArray(value)) return error("invalid_request", 422);
  const fields = value as Record<string, unknown>;
  const name = typeof fields.name === "string" ? fields.name.trim() : "";
  const categoryId = method === "PATCH" ? fields.id : null;
  if (!name || name.length > 255 ||
      (method === "PATCH" && (!Number.isSafeInteger(categoryId) || Number(categoryId) < 1))) {
    return error("invalid_request", 422);
  }
  const payload = { name, position: 0, is_published: false };
  try {
    const result = await bridgeFetch<{ id: number }>(
      method === "PATCH" ? `/categories/${categoryId}` : "/categories",
      method, method === "PATCH" ? { name } : payload, session,
    );
    return NextResponse.json({ ok: true, id: result.id }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (failure) {
    if (failure instanceof ApiError) {
      const code = failure.status === 409 ? "category_exists" :
        failure.status === 403 ? "permission_denied" :
        failure.status === 422 ? "invalid_request" : "service_unavailable";
      return error(code, failure.status);
    }
    return error("service_unavailable", 503);
  }
}
export function POST(request: NextRequest): Promise<NextResponse> { return mutate(request, "POST"); }
export function PATCH(request: NextRequest): Promise<NextResponse> { return mutate(request, "PATCH"); }
