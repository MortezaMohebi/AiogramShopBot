import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";
type Context = { params: Promise<{ id: string }> };

/** Download a bounded, non-cacheable customer export, never private CRM notes. */
export async function GET(
  _request: NextRequest, context: Context,
): Promise<Response> {
  const { id } = await context.params;
  if (!/^[1-9][0-9]*$/.test(id)) {
    return new Response("Not found", { status: 404 });
  }
  const session = await readSession();
  if (!session) return new Response("Unauthorized", { status: 401 });
  try {
    const result = await bridgeFetch<{ ok: boolean; export: unknown }>(
      `/customers/${id}/export`, "GET", null, session,
    );
    if (!result.ok) throw new Error("Export unavailable");
    const body = JSON.stringify(result.export, null, 2);
    if (Buffer.byteLength(body, "utf8") > 4_000_000) {
      return new Response("Export too large", { status: 413 });
    }
    return new Response(body, {
      headers: {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Disposition": `attachment; filename="shop-customer-${id}.json"`,
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError &&
      [401, 403, 404, 428].includes(error.status) ? error.status : 503;
    return NextResponse.json({ ok: false, code: "export_unavailable" }, {
      status, headers: { "Cache-Control": "no-store" },
    });
  }
}
