import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";

type Params = { params: Promise<{ id: string }> };

function rejected(code: string, status: number) {
  return NextResponse.json(
    { ok: false, code },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

/** Restrict all product media mutations to an authenticated content editor. */
async function mutate(request: NextRequest, context: Params, method: "PATCH" | "DELETE") {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return rejected("security_check_failed", 403);
  }
  const session = await readSession();
  if (!session) return rejected("session_expired", 401);
  const { id } = await context.params;
  if (!/^[1-9]\d*$/.test(id)) return rejected("invalid_request", 422);
  let data: Record<string, boolean> | null = null;
  if (method === "PATCH") {
    if (!(request.headers.get("content-type") ?? "").startsWith("application/json")) {
      return rejected("invalid_request", 415);
    }
    const content = await request.text();
    if (Buffer.byteLength(content, "utf8") > 128) return rejected("invalid_request", 422);
    try {
      const raw: unknown = JSON.parse(content);
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
        return rejected("invalid_request", 422);
      }
      const fields = raw as Record<string, unknown>;
      if (
        Object.keys(fields).length !== 1 ||
        typeof fields.is_published !== "boolean"
      ) return rejected("invalid_request", 422);
      data = { is_published: fields.is_published };
    } catch { return rejected("invalid_request", 422); }
  }
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (!["superadmin", "content"].includes(staff.role)) {
      return rejected("permission_denied", 403);
    }
    await bridgeFetch("/media/" + id, method, data, session);
    return NextResponse.json({ ok: true }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 401) return rejected("session_expired", 401);
      if (error.status === 403) return rejected("permission_denied", 403);
      if (error.status === 404) return rejected("not_found", 404);
      if (error.status === 409) return rejected("conflict", 409);
    }
    return rejected("service_unavailable", 503);
  }
}

export async function PATCH(request: NextRequest, context: Params) {
  return mutate(request, context, "PATCH");
}

export async function DELETE(request: NextRequest, context: Params) {
  return mutate(request, context, "DELETE");
}
