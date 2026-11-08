import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch, bridgeResponse } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";
import { publicOrigin, trustedBrowserOrigin } from "@/lib/public-origin";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";

export const runtime = "nodejs";
const MAX_BODY_BYTES = 50_100_000;
type UploadTarget = "product" | "testimonial" | "campaign";

/** Read one multipart body with a hard limit even without Content-Length. */
async function boundedBytes(request: NextRequest): Promise<Uint8Array> {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_BODY_BYTES)) {
    throw new ApiError(413, "Upload exceeds the request limit");
  }
  if (!request.body) throw new ApiError(400, "Empty upload");
  const parts: Uint8Array[] = [];
  let total = 0;
  const reader = request.body.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > MAX_BODY_BYTES) throw new ApiError(413, "Upload too large");
      parts.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.byteLength;
  }
  return result;
}

/** Browser POST -> same-origin BFF -> signed FastAPI private storage. */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const target = request.nextUrl.searchParams.get("target") as UploadTarget | null;
  if (!target || !["product", "testimonial", "campaign"].includes(target)) {
    return new NextResponse("Not found", { status: 404 });
  }
  const fallback = target === "campaign" ? "/campaigns" :
    target === "testimonial" ? "/reviews" : "/media";
  const jsonResponse = (request.headers.get("accept") ?? "").includes("application/json");
  // Programmatic multi-file uploads require a host-bound CSRF challenge,
  // while existing native browser forms keep their Origin/Fetch Metadata gate.
  if (jsonResponse && (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request))) {
    return NextResponse.json(
      { ok: false, code: "security_check_failed" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  const origin = trustedBrowserOrigin(request);
  if (!origin) {
    // Older/native forms should never leave a user on an opaque 403 screen.
    const configured = publicOrigin(request);
    return configured
      ? NextResponse.redirect(new URL(`${fallback}?error=security`, configured), 303)
      : NextResponse.json(
          { ok: false, code: "security_check_failed" },
          { status: 403, headers: { "Cache-Control": "no-store" } },
        );
  }
  const type = request.headers.get("content-type") ?? "";
  if (!/^multipart\/form-data;\s*boundary=[a-zA-Z0-9'()+_,.\/=:?-]{1,200}$/i.test(type)) {
    return new NextResponse("Expected multipart form", { status: 415 });
  }
  const session = await readSession();
  if (!session) {
    return NextResponse.redirect(new URL("/login?expired=1", origin), 303);
  }
  try {
    // Revalidate the role BEFORE accepting the potentially large upload.
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    const allowed = target === "campaign" ? "marketing" : "content";
    if (staff.role !== "superadmin" && staff.role !== allowed) {
      return NextResponse.redirect(new URL(`${fallback}?error=permission`, origin), 303);
    }
    const body = await boundedBytes(request);
    const response = await bridgeResponse(
      `/upload/${target}`, "POST", body, type, session, 120_000,
    );
    const result = await response.json() as {id: number; campaign_id?: number};
    if (jsonResponse) {
      return NextResponse.json(
        { ok: true, id: result.id, campaign_id: result.campaign_id },
        { status: 201, headers: { "Cache-Control": "no-store" } },
      );
    }
    // Always redirect only to a fixed local page, never to user-supplied URLs.
    const next = new URL(`${fallback}?saved=1`, origin);
    if (target === "campaign" && Number.isSafeInteger(result.campaign_id) && Number(result.campaign_id) > 0) {
      next.pathname = `/campaigns/${result.campaign_id}`;
    }
    next.searchParams.set("record", String(result.id));
    return NextResponse.redirect(next, 303);
  } catch (error) {
    const code = error instanceof ApiError
      ? error.status === 413 ? "size" : error.status === 422 ? "file" : "upload"
      : "upload";
    if (jsonResponse) {
      return NextResponse.json(
        { ok: false, code },
        { status: code === "size" ? 413 : code === "file" ? 422 : 503,
          headers: { "Cache-Control": "no-store" } },
      );
    }
    return NextResponse.redirect(
      new URL(`${fallback}?error=${code}`, origin), 303,
    );
  }
}
