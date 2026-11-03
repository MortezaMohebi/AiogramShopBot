import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";

/** List only media belonging to a validated database product ID. */
export async function GET(request: NextRequest): Promise<NextResponse> {
  const product = request.nextUrl.searchParams.get("product_id");
  if (!product || !/^[1-9][0-9]*$/.test(product)) {
    return NextResponse.json({ ok: false, code: "invalid_request" }, { status: 422 });
  }
  const session = await readSession();
  if (!session) return NextResponse.json({ ok: false, code: "session_expired" }, { status: 401 });
  try {
    const items = await bridgeFetch(`/products/${product}/media`, "GET", null, session);
    return NextResponse.json({ ok: true, items }, { headers: { "Cache-Control": "no-store" } });
  } catch (failure) {
    return NextResponse.json({ ok: false, code: "media_unavailable" }, {
      status: failure instanceof ApiError && [401, 403, 404].includes(failure.status) ? failure.status : 503,
    });
  }
}
