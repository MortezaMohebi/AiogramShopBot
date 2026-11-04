import { NextResponse, type NextRequest } from "next/server";
import { bridgeFetch, bridgeResponse, ApiError } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";
import { trustedBrowserOrigin } from "@/lib/public-origin";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";
const MAX_BODY = 50_100_000;
type Context = { params: Promise<{ id: string }> };

function denied(status: number, code: string): NextResponse {
  return NextResponse.json({ ok: false, code }, {
    status, headers: { "Cache-Control": "private, no-store" },
  });
}

/** Bounded same-origin multipart upload to the signed private digital API. */
export async function POST(request: NextRequest, { params }: Context) {
  const { id } = await params;
  if (!/^[1-9][0-9]{0,14}$/.test(id)) return denied(404, "invalid_request");
  if (
    !trustedBrowserOrigin(request) ||
    !safeLoginFetchMetadata(request) ||
    !verifyLoginChallenge(request)
  ) {
    return denied(403, "security_check_failed");
  }
  const type = request.headers.get("content-type") ?? "";
  if (!/^multipart\/form-data;\s*boundary=[a-zA-Z0-9'()+_,.\/:=?-]{1,200}$/i.test(type)) {
    return denied(415, "invalid_digital_file");
  }
  const declared = request.headers.get("content-length");
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > MAX_BODY)) {
    return denied(413, "size");
  }
  const session = await readSession();
  if (!session) return denied(401, "session_expired");
  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (!["superadmin", "content"].includes(staff.role)) {
      return denied(403, "permission_denied");
    }
    if (!request.body) return denied(422, "invalid_digital_file");
    const reader = request.body.getReader();
    const parts: Uint8Array[] = [];
    let length = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > MAX_BODY) {
          await reader.cancel().catch(() => undefined);
          return denied(413, "size");
        }
        parts.push(value);
      }
    } finally {
      reader.releaseLock();
    }
    if (!length) return denied(422, "invalid_digital_file");
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.byteLength;
    }
    const response = await bridgeResponse(
      `/digital-products/${id}/file`,
      "POST", bytes, type, session, 120_000,
    );
    const result: unknown = await response.json();
    return NextResponse.json({ ok: true, result }, {
      status: 201,
      headers: { "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      return denied(
        [400, 401, 403, 404, 409, 413, 422].includes(error.status)
          ? error.status : 503,
        error.code && ["digital_asset_not_ready", "store_access_denied",
          "store_switch_required", "invalid_digital_file"].includes(error.code)
          ? error.code : "upload",
      );
    }
    return denied(503, "upload");
  }
}
