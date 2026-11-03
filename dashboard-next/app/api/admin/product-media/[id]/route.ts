import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import { controlJson } from "@/lib/control-request";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";

export const runtime = "nodejs";
type Context = { params: Promise<{ id: string }> };
function fail(status: number): NextResponse {
  return NextResponse.json({ ok: false, code: "media_change_failed" }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Mutations require same-site CSRF proof, server-side permission and ID validation. */
async function change(request: NextRequest, context: Context, method: "PATCH" | "DELETE"): Promise<NextResponse> {
  const { id } = await context.params;
  if (!/^[1-9][0-9]*$/.test(id)) return fail(404);
  const session = await readSession();
  if (!session) return fail(401);
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) return fail(403);
  let body: Record<string, unknown> | null = null;
  if (method === "PATCH") {
    let raw: unknown;
    try { raw = await controlJson(request, 4096); } catch { return fail(422); }
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return fail(422);
    const values = raw as Record<string, unknown>;
    if (Object.keys(values).some((key) => !["caption", "position", "is_published"].includes(key))) return fail(422);
    if (typeof values.caption !== "undefined" && (typeof values.caption !== "string" || values.caption.length > 2000)) return fail(422);
    if (typeof values.position !== "undefined" && (!Number.isSafeInteger(values.position) || Number(values.position) < 0 || Number(values.position) > 1000000)) return fail(422);
    if (typeof values.is_published !== "undefined" && typeof values.is_published !== "boolean") return fail(422);
    body = values;
  }
  try {
    await bridgeFetch(`/media/${id}`, method, body, session);
    return NextResponse.json({ ok: true }, { headers: { "Cache-Control": "no-store" } });
  } catch (failure) {
    return fail(failure instanceof ApiError && [401, 403, 404, 409, 422].includes(failure.status)
      ? failure.status : 503);
  }
}
export function PATCH(request: NextRequest, context: Context) { return change(request, context, "PATCH"); }
export function DELETE(request: NextRequest, context: Context) { return change(request, context, "DELETE"); }
