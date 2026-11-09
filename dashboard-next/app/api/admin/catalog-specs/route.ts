import { NextResponse, type NextRequest } from "next/server";
import { ApiError, bridgeFetch } from "@/lib/bridge";
import { safeLoginFetchMetadata, verifyLoginChallenge } from "@/lib/login-challenge";
import { readSession } from "@/lib/session";

export const runtime = "nodejs";
const headers = { "Cache-Control": "no-store" };
const safeCodes = new Set(["catalog_spec_in_use", "catalog_spec_conflict", "catalog_term_parent_fixed", "invalid_catalog_spec"]);
const allowedKeys = new Set(["label", "unit", "aliases", "definition_id"]);
const isId = (value: string | null) => value !== null && /^[1-9]\d{0,9}$/.test(value) && Number(value) <= 2147483647;
const error = (code: string, status: number) => NextResponse.json({ code }, { status, headers });

async function catalog(request: NextRequest, method: "GET" | "POST" | "PATCH" | "DELETE") {
  const params = request.nextUrl.searchParams;
  const store = params.get("store"), kind = params.get("kind"), id = params.get("id");
  const item = method === "PATCH" || method === "DELETE";
  if (!store || !/^[a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12}$/i.test(store)
    || (kind !== "attributes" && kind !== "values") || (item ? !isId(id) : id !== null)) {
    return error("invalid_catalog_spec", 422);
  }
  if (method !== "GET" && (!safeLoginFetchMetadata(request) || !verifyLoginChallenge(request))) {
    return error("security_check_failed", 403);
  }
  const session = await readSession();
  if (!session) return error("session_expired", 401);
  let path = `/catalog-specs/${store}/${kind}${item ? `/${id}` : ""}`;
  let payload: unknown = null;
  if (method === "GET") {
    const q = params.get("q") ?? "", page = params.get("page") ?? "1";
    const parent = params.get("definition_id");
    if (q.length > 80 || !isId(page) || Number(page) > 10_000 || (parent !== null && !isId(parent))) {
      return error("invalid_catalog_spec", 422);
    }
    const query = new URLSearchParams({ q, page });
    if (parent) query.set("definition_id", parent);
    path += `?${query}`;
  } else if (method !== "DELETE") {
    if (!(request.headers.get("content-type") ?? "").startsWith("application/json")
      || Number(request.headers.get("content-length")) > 16000) return error("invalid_catalog_spec", 422);
    try {
      const body = await request.text();
      if (Buffer.byteLength(body) > 16000) return error("invalid_catalog_spec", 422);
      payload = JSON.parse(body) as unknown;
    } catch {
      return error("invalid_catalog_spec", 422);
    }
    if (!payload || typeof payload !== "object" || Array.isArray(payload)
      || Object.keys(payload).some((key) => !allowedKeys.has(key))) return error("invalid_catalog_spec", 422);
  }
  try {
    return NextResponse.json(await bridgeFetch(path, method, payload, session), { headers });
  } catch (failure) {
    if (failure instanceof ApiError) {
      if (failure.status === 401) return error("session_expired", 401);
      if (failure.status === 403) return error("permission_denied", 403);
      if (failure.status === 404) return error("not_found", 404);
      if (failure.status === 409) return error(safeCodes.has(failure.code ?? "") ? failure.code! : "catalog_spec_conflict", 409);
      if (failure.status === 422) return error("invalid_catalog_spec", 422);
    }
    return error("service_unavailable", 503);
  }
}

export const GET = (request: NextRequest) => catalog(request, "GET");
export const POST = (request: NextRequest) => catalog(request, "POST");
export const PATCH = (request: NextRequest) => catalog(request, "PATCH");
export const DELETE = (request: NextRequest) => catalog(request, "DELETE");
