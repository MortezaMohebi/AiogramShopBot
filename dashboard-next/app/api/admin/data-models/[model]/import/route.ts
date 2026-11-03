import { NextResponse, type NextRequest } from "next/server";
import { bridgeResponse, ApiError } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";
const MAX_BYTES = 8 * 1024 * 1024;
const VALID_MODELS = new Set(["products", "customers"]);
const VALID_FORMATS = new Set(["csv", "xlsx"]);
const SHA = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

interface Context {
  params: Promise<{ model: string }>;
}

function reject(code: string, status: number) {
  return NextResponse.json({ ok: false, code }, {
    status, headers: { "Cache-Control": "no-store" },
  });
}

/** Relay one bounded file to the signed API without repeating write requests. */
export async function POST(
  request: NextRequest, { params }: Context,
): Promise<NextResponse> {
  if (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request)) {
    return reject("security_check_failed", 403);
  }
  const session = await readSession();
  if (!session) return reject("session_expired", 401);

  const { model } = await params;
  const format = request.nextUrl.searchParams.get("format") ?? "";
  const mode = request.nextUrl.searchParams.get("mode") ?? "preview";
  const hash = request.nextUrl.searchParams.get("hash") ?? "";
  const previewId = request.nextUrl.searchParams.get("preview_id") ?? "";
  if (
    !VALID_MODELS.has(model) || !VALID_FORMATS.has(format)
    || !["preview", "apply"].includes(mode)
    || (mode === "apply" && (!SHA.test(hash) || !UUID.test(previewId)))
  ) {
    return reject("invalid_request", 422);
  }

  const contentLength = request.headers.get("content-length");
  if (!contentLength || !/^\d+$/.test(contentLength) ||
    Number(contentLength) > MAX_BYTES) {
    return reject("invalid_import_file", 413);
  }
  if ((request.headers.get("content-type") ?? "").split(";", 1)[0] !==
      "application/octet-stream") {
    return reject("invalid_import_file", 415);
  }
  try {
    const bytes = new Uint8Array(await request.arrayBuffer());
    if (bytes.byteLength === 0 || bytes.byteLength > MAX_BYTES) {
      return reject("invalid_import_file", 413);
    }
    const parameters = new URLSearchParams({
      format, dry_run: mode === "preview" ? "true" : "false",
    });
    if (mode === "apply") {
      parameters.set("expected_sha256", hash);
      parameters.set("preview_id", previewId);
    }
    const upstream = await bridgeResponse(
      `/data-models/${model}/import?${parameters.toString()}`,
      "POST", bytes, "application/octet-stream", session, 45_000,
    );
    const result: unknown = await upstream.json();
    return NextResponse.json({ ok: true, result }, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    if (error instanceof ApiError) {
      const safe = new Set([
        "invalid_import_file", "invalid_import_columns",
        "import_too_many_rows", "import_formula_not_allowed",
        "import_identity_required", "import_duplicate_key",
        "import_conflict", "import_identity_conflict", "import_required_field",
        "import_stock_adjustment_required", "import_publish_requires_review",
        "import_preview_required", "import_data_changed",
        "invalid_import_value",
        "invalid_external_reference", "uom_not_available",
        "uom_category_mismatch", "store_access_denied",
      ]);
      return reject(
        error.code && safe.has(error.code) ? error.code : "import_failed",
        error.status,
      );
    }
    return reject("import_unavailable", 503);
  }
}
