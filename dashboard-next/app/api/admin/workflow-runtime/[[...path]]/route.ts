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
  if (method === "GET") {
    if (path.length === 0) return [];
    if (path.length === 1) {
      if (path[0] === "publications") return ["page", "workflow_id"];
      if (path[0] === "bindings" || path[0] === "history") return ["page"];
      if (path[0] === "runs") return ["page", "status", "workflow_id", "publication_id"];
      if (path[0] === "outbox") return ["page", "status"];
    }
    if (path.length === 2 && path[0] === "runs" && uuid.test(path[1])) return [];
  }
  if (method === "POST") {
    if (path.length === 1 && path[0] === "gates") return [];
    if (path.length === 2 && path[0] === "publications" && ["preview", "activate"].includes(path[1])) return [];
    if (path.length === 3 && uuid.test(path[1]) && (
      (path[0] === "publications" && path[2] === "retire") ||
      (path[0] === "runs" && path[2] === "recover") ||
      (path[0] === "actions" && path[2] === "approve") ||
      (path[0] === "outbox" && path[2] === "retry")
    )) return [];
  }
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
        "runtime_invalid_request",
        code === "body_limit" ? 413 : code === "content_type" ? 415 : 422,
      );
    }
  }
  try {
    const target = `/workflow-runtime${path.length ? `/${path.join("/")}` : ""}${url.search}`;
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
