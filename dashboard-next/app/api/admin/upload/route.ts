import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch, bridgeResponse } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

export const runtime = "nodejs";
const MAX_BODY_BYTES = 50_100_000;
type UploadTarget = "product" | "testimonial" | "campaign";

/** Require an exact configured public Origin; reject spoofed cross-site posts. */
function allowedOrigin(request: NextRequest): string | null {
  const publicOrigin = process.env.NEXT_ADMIN_PUBLIC_ORIGIN;
  if (process.env.NODE_ENV === "production" && !publicOrigin) return null;
  const expected = publicOrigin ?? request.nextUrl.origin;
  try {
    const url = new URL(expected);
    if (url.origin !== expected) return null;
    if (process.env.NODE_ENV === "production" && url.protocol !== "https:") {
      return null;
    }
  } catch {
    return null;
  }
  if (request.headers.get("origin") !== expected) return null;
  const site = request.headers.get("sec-fetch-site");
  if (site && site !== "same-origin") return null;
  return expected;
}

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
  const origin = allowedOrigin(request);
  if (!origin) return new NextResponse("Forbidden", { status: 403 });
  const target = request.nextUrl.searchParams.get("target") as UploadTarget | null;
  if (!target || !["product", "testimonial", "campaign"].includes(target)) {
    return new NextResponse("Not found", { status: 404 });
  }
  const fallback = target === "campaign" ? "/campaigns" :
    target === "testimonial" ? "/reviews" : "/media";
  const type = request.headers.get("content-type") ?? "";
  if (!/^multipart\/form-data;\s*boundary=[a-zA-Z0-9'()+_,.\/=:?-]{1,200}$/i.test(type)) {
    return new NextResponse("Expected multipart form", { status: 415 });
  }
  const session = await readSession();
  if (!session) return new NextResponse("Unauthorized", { status: 401 });
  try {
    // Revalidate the role BEFORE accepting the potentially large upload.
    const staff = await bridgeFetch<Staff>("/auth/me", "GET", null, session);
    const allowed = target === "campaign" ? "marketing" : "content";
    if (staff.role !== "superadmin" && staff.role !== allowed) {
      return new NextResponse("Forbidden", { status: 403 });
    }
    const body = await boundedBytes(request);
    const response = await bridgeResponse(
      `/upload/${target}`, "POST", body, type, session, 120_000,
    );
    const result = await response.json() as {id: number; campaign_id?: number};
    // Always redirect only to a fixed local page, never to user-supplied URLs.
    const next = new URL(`${fallback}?saved=1`, origin);
    if (target === "campaign" && Number.isSafeInteger(result.campaign_id) && Number(result.campaign_id) > 0) {
      next.pathname = `/campaigns/${result.campaign_id}`;
    }
    next.searchParams.set("record", String(result.id));
    return NextResponse.redirect(next, 303);
  } catch (error) {
    if (!(error instanceof ApiError)) {
      // No exception stack, response body or private storage path is returned.
      return NextResponse.redirect(new URL(`${fallback}?error=upload`, origin), 303);
    }
    const code = error.status === 413 ? "size" : error.status === 422 ? "file" : "upload";
    return NextResponse.redirect(new URL(`${fallback}?error=${code}`, origin), 303);
  }
}
