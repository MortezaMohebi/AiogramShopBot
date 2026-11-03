import { NextResponse, type NextRequest } from "next/server";
import { bridgeResponse, ApiError } from "@/lib/bridge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";
const VALID_MODELS = new Set(["products", "customers", "orders"]);
const VALID_ACTIONS = new Set(["template", "export"]);
const VALID_FORMATS = new Set(["csv", "xlsx"]);

interface Context {
  params: Promise<{ model: string; action: string }>;
}

/** Authenticated download proxy: the browser never learns the API bridge key. */
export async function GET(request: NextRequest, { params }: Context): Promise<Response> {
  const { model, action } = await params;
  const format = request.nextUrl.searchParams.get("format") ?? "";
  if (!VALID_MODELS.has(model) || !VALID_ACTIONS.has(action) ||
      !VALID_FORMATS.has(format)) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }
  const session = await readSession();
  if (!session) {
    return NextResponse.json({ error: "session_expired" }, { status: 401 });
  }
  try {
    const upstream = await bridgeResponse(
      `/data-models/${model}/${action}?format=${format}`,
      "GET", null, null, session, 30_000,
    );
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": format === "csv"
          ? "text/csv; charset=utf-8"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition":
          `attachment; filename="${model}-${action}.${format}"`,
        "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError &&
      [401, 403, 404, 409, 422, 503].includes(error.status)
      ? error.status : 503;
    return NextResponse.json({ error: "download_unavailable" }, {
      status, headers: { "Cache-Control": "no-store" },
    });
  }
}
