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
  const query = request.nextUrl.searchParams;
  const format = query.get("format") ?? "";
  const fields = query.getAll("fields");
  const compatible = query.get("update_compatible");
  if (!VALID_MODELS.has(model) || !VALID_ACTIONS.has(action) ||
      !VALID_FORMATS.has(format) || fields.length > 40 ||
      new Set(fields).size !== fields.length ||
      fields.some((field) => !/^[a-z][a-z0-9_]{0,63}$/.test(field)) ||
      (compatible !== null && !["true", "false"].includes(compatible)) ||
      (action !== "export" && (fields.length > 0 || compatible !== null))) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }
  const session = await readSession();
  if (!session) {
    return NextResponse.json({ error: "session_expired" }, { status: 401 });
  }
  try {
    const parameters = new URLSearchParams({ format });
    for (const field of fields) parameters.append("fields", field);
    if (compatible === "true") parameters.set("update_compatible", "true");
    const upstream = await bridgeResponse(
      `/data-models/${model}/${action}?${parameters.toString()}`,
      "GET", null, null, session, 30_000,
    );
    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": format === "csv"
          ? "text/csv; charset=utf-8"
          : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "Content-Disposition":
          `attachment; filename="${model}-${compatible === "true" ? "update" : action}.${format}"`,
        "Cache-Control": "no-store, private",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const status = error instanceof ApiError &&
      [401, 403, 404, 409, 422, 503].includes(error.status)
      ? error.status : 503;
    const code = error instanceof ApiError && [
      "model_export_too_large", "unknown_model_field", "model_import_not_supported",
      "store_access_denied", "permission_denied", "session_expired",
    ].includes(error.code ?? "") ? error.code : "download_unavailable";
    return NextResponse.json({ error: code }, {
      status, headers: { "Cache-Control": "no-store" },
    });
  }
}
