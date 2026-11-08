import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch, bridgeResponse } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { trustedBrowserOrigin } from "@/lib/public-origin";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";

const PRODUCT_ID = /^[1-9][0-9]{0,15}$/;
const MAX_BODY_BYTES = 50_100_000;

type Context = { params: Promise<{ id: string }> };

function reject(code: string, status: number): NextResponse {
  return NextResponse.json(
    { ok: false, code },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

/** Read bounded multipart bytes without trusting user Content-Length. */
async function readLimited(request: NextRequest): Promise<Uint8Array> {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_BODY_BYTES)) {
    throw new ApiError(413, "Upload exceeds private storage limit");
  }
  const reader = request.body?.getReader();
  if (!reader) throw new ApiError(422, "Missing file body");
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) throw new ApiError(413, "Digital file too large");
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  if (!total) throw new ApiError(422, "Empty digital upload");
  const result = new Uint8Array(total);
  let offset = 0;
  for (const value of chunks) {
    result.set(value, offset);
    offset += value.byteLength;
  }
  return result;
}

/** Same-origin browser -> signed FastAPI, no direct public digital file URL. */
export async function POST(
  request: NextRequest, { params }: Context,
): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) ||
      !verifyLoginChallenge(request) ||
      !trustedBrowserOrigin(request)) {
    return reject("security_check_failed", 403);
  }
  const { id } = await params;
  if (!PRODUCT_ID.test(id)) return reject("invalid_product", 422);
  const type = request.headers.get("content-type") ?? "";
  if (!/^multipart\/form-data;\s*boundary=[a-zA-Z0-9'()+_,.\/=:\?-]{1,200}$/i.test(type)) {
    return reject("invalid_file_type", 415);
  }
  const session = await readSession();
  if (!session) return reject("session_expired", 401);

  try {
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    if (!["superadmin", "content"].includes(staff.role)) {
      return reject("permission_denied", 403);
    }
    const payload = await readLimited(request);
    const response = await bridgeResponse(
      `/products/${id}/digital-file`,
      "POST", payload, type, session, 120_000,
    );
    const snapshot: unknown = await response.json();
    return NextResponse.json(
      { ok: true, result: snapshot },
      { status: 201, headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    const status = error instanceof ApiError ? error.status : 503;
    return reject(
      status === 413 ? "size" :
      status === 428 ? "reauth" :
      status === 422 ? "invalid_file" : "upload_failed",
      status,
    );
  }
}
