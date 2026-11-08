import { type NextRequest } from "next/server";
import { ApiError, bridgeResponse } from "@/lib/bridge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";

/** Proxy only authenticated private media; never expose file paths or bot IDs. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ kind: string; id: string }> },
): Promise<Response> {
  const { kind, id } = await params;
  if (!["product", "testimonial", "campaign"].includes(kind) || !/^[1-9]\d*$/.test(id)) {
    return new Response("Not found", { status: 404 });
  }
  const session = await readSession();
  if (!session) return new Response("Unauthorized", { status: 401 });
  try {
    const backend = await bridgeResponse(
      `/media/preview/${kind}/${id}`,
      "GET", null, null, session, 45_000,
    );
    return new Response(backend.body, {
      status: 200,
      headers: {
        "Content-Type": backend.headers.get("content-type") ?? "application/octet-stream",
        "Content-Disposition": "inline",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "X-Frame-Options": "DENY",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError && [401, 403, 404].includes(error.status)
      ? error.status : 502;
    return new Response(status === 404 ? "Not found" : "Preview unavailable", {
      status,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
