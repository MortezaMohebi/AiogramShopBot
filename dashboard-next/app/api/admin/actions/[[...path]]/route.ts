import { randomUUID } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeResponse } from "@/lib/bridge";
import { readSession } from "@/lib/session";
import {
  safeLoginFetchMetadata,
  verifyLoginChallenge,
} from "@/lib/login-challenge";
export const runtime = "nodejs";
type Method = "GET" | "POST";
type Context = { params: Promise<{ path?: string[] }> };
const uuid =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ceiling = 256 * 1024;
/** Match a closed route family, never an arbitrary signed administrative URL. */
function permitted(method: Method, path: string[]): string[] | null {
  if (path.length === 0 && method === "GET")
    return [
      "q",
      "category",
      "side_effect",
      "deprecated",
      "page",
      "page_size",
      "store_id",
      "bot_id",
      "platform",
    ];
  if (path.length === 1 && path[0] === "bots" && method === "GET")
    return ["page", "q"];
  if (path.length === 1 && path[0] === "dry-run" && method === "POST")
    return [];
  if (
    path.length === 2 &&
    path[0] === "receipts" &&
    uuid.test(path[1]) &&
    method === "GET"
  )
    return [];
  if (
    path.length === 2 &&
    method === "GET" &&
    /^[a-z][a-z0-9_]{0,31}\.[a-z][a-z0-9_]{0,47}$/.test(path[0]) &&
    /^[0-9]+\.[0-9]+\.[0-9]+$/.test(path[1])
  )
    return ["bot_id", "platform"];
  return null;
}
function failure(
  code: string,
  status: number,
  requestId: string = randomUUID(),
) {
  return NextResponse.json(
    { ok: false, code, requestId },
    {
      status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    },
  );
}
/** Count actual streamed bytes, including requests without Content-Length. */
async function body(request: NextRequest): Promise<string> {
  if (
    (request.headers.get("content-type") ?? "")
      .split(";", 1)[0]
      .trim()
      .toLowerCase() !== "application/json"
  )
    throw new Error("content_type");
  const announced = request.headers.get("content-length");
  if (announced && (!/^\d+$/.test(announced) || Number(announced) > ceiling)) {
    await request.body?.cancel();
    throw new Error("body_limit");
  }
  if (!request.body) throw new Error("invalid_json");
  const reader = request.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > ceiling) throw new Error("body_limit");
      parts.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  const text = new TextDecoder("utf-8", { fatal: true }).decode(
    Buffer.concat(parts),
  );
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("invalid_json");
  return text;
}
async function handle(
  request: NextRequest,
  context: Context,
  method: Method,
): Promise<NextResponse> {
  const path = (await context.params).path ?? [];
  const keys = permitted(method, path),
    url = new URL(request.url);
  if (
    keys === null ||
    Array.from(url.searchParams.keys()).some((k) => !keys.includes(k)) ||
    Array.from(url.searchParams.keys()).some(
      (k) => url.searchParams.getAll(k).length !== 1,
    )
  )
    return failure("invalid_request", 404);
  const session = await readSession();
  if (!session) return failure("session_expired", 401);
  if (
    method !== "GET" &&
    (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request))
  )
    return failure("security_check_failed", 403);
  let raw: string | null = null;
  if (method !== "GET") {
    try {
      raw = await body(request);
    } catch (error) {
      const code = error instanceof Error ? error.message : "invalid_json";
      return failure(
        "action_invalid_request",
        code === "body_limit" ? 413 : code === "content_type" ? 415 : 422,
      );
    }
  }
  try {
    const target = `/actions${path.length ? `/${path.join("/")}` : ""}${url.search}`;
    const upstream = await bridgeResponse(
      target,
      method,
      raw,
      raw === null ? null : "application/json",
      session,
      20000,
    );
    const data: unknown = await upstream.json();
    return NextResponse.json(data, {
      status: upstream.status,
      headers: {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    if (error instanceof ApiError)
      return failure(
        error.code ??
          (error.status === 401
            ? "session_expired"
            : error.status === 403
              ? "permission_denied"
              : "service_unavailable"),
        error.status,
        error.requestId,
      );
    return failure("service_unavailable", 503);
  }
}
export async function GET(r: NextRequest, c: Context) {
  return handle(r, c, "GET");
}
export async function POST(r: NextRequest, c: Context) {
  return handle(r, c, "POST");
}
