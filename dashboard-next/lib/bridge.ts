import "server-only";

import { createHash, createHmac, randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

interface Identity {
  id: number;
  version: number;
}

type Method = "GET" | "POST" | "PATCH" | "DELETE";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Log only safe diagnostics; never a query string, body, key or provider error. */
function bridgeFailure(
  path: string,
  method: Method,
  status: number,
  code: "configuration" | "network" | "timeout" | "http" | "invalid_json",
  requestId = randomUUID(),
): ApiError {
  const route = path.split("?", 1)[0]
    .replace(/\/[0-9]+(?=\/|$)/g, "/:id").slice(0, 160);
  console.warn("[shop-admin/bridge]", { requestId, method, route, status, code });
  return new ApiError(status, `Administrative API ${code} (${requestId})`, requestId);
}

function environment(): { host: URL; secret: string } {
  const host = process.env.SHOP_FASTAPI_INTERNAL_URL;
  const secret = process.env.NEXT_ADMIN_BRIDGE_SECRET ?? "";
  if (!host || secret.length < 32) {
    throw new Error("Next dashboard backend bridge is not configured.");
  }
  const origin = new URL(host);
  if (origin.protocol !== "http:" && origin.protocol !== "https:") {
    throw new Error("Unsupported FastAPI bridge URL scheme.");
  }
  return { host: origin, secret };
}

/** Sign exact request bytes; do not retry a mutation after an uncertain response. */
export async function bridgeResponse(
  path: string,
  method: Method,
  body: Uint8Array | string | null,
  contentType: string | null,
  identity: Identity | null,
  timeoutMs = 15_000,
): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Invalid internal API path.");
  }
  let connection: ReturnType<typeof environment>;
  try {
    connection = environment();
  } catch {
    throw bridgeFailure(`/internal/admin/v1${path}`, method, 503, "configuration");
  }
  const { host, secret } = connection;
  const url = new URL(`/internal/admin/v1${path}`, host);
  if (!url.pathname.startsWith("/internal/admin/v1/")) {
    throw new Error("Invalid internal admin route.");
  }
  const bytes = typeof body === "string"
    ? Buffer.from(body, "utf8")
    : body === null ? new Uint8Array() : body;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const target = url.pathname + url.search;
  const digest = createHash("sha256").update(bytes).digest("hex");
  const staff = String(identity?.id ?? 0);
  const version = String(identity?.version ?? 0);
  const signature = createHmac("sha256", secret)
    .update([timestamp, method, target, digest, staff, version].join("\n"))
    .digest("hex");
  const requestId = randomUUID();
  const signal = AbortSignal.timeout(timeoutMs);

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(contentType ? { "content-type": contentType } : {}),
        "x-shop-time": timestamp,
        "x-shop-signature": signature,
        "x-shop-staff": staff,
        "x-shop-version": version,
        "x-shop-request-id": requestId,
      },
      // Request bytes must remain byte-for-byte identical after signing.
      body: method === "GET" || body === null ? undefined : new Uint8Array(bytes),
      cache: "no-store",
      redirect: "error",
      signal,
    });
  } catch {
    throw bridgeFailure(
      url.pathname, method, signal.aborted ? 504 : 503,
      signal.aborted ? "timeout" : "network", requestId,
    );
  }

  if (!response.ok) {
    // An error body's text is not needed for status-specific frontend feedback
    // and can include private upstream details. Discard it rather than log it.
    await response.body?.cancel().catch(() => undefined);
    throw bridgeFailure(url.pathname, method, response.status, "http", requestId);
  }
  return response;
}

/** JSON wrapper with an optional bounded deadline for read-only provider probes. */
export async function bridgeFetch<T>(
  path: string,
  method: Method,
  data: unknown,
  identity: Identity | null,
  timeoutMs = 15_000,
): Promise<T> {
  const raw = method === "GET" || method === "DELETE"
    ? null
    : JSON.stringify(data ?? {});
  const response = await bridgeResponse(
    path, method, raw, raw === null ? null : "application/json", identity, timeoutMs,
  );
  try {
    return (await response.json()) as T;
  } catch {
    throw bridgeFailure(`/internal/admin/v1${path}`, method, 502, "invalid_json");
  }
}

/** Verify a live staff account on EVERY server-rendered admin request. */
export async function currentStaff(): Promise<Staff> {
  const session = await readSession();
  if (!session) redirect("/login");
  try {
    return await bridgeFetch<Staff>("/auth/me", "GET", null, session);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect("/login?expired=1");
    }
    throw error;
  }
}

/** Revalidate role/session in Python and distinguish expiry from a data outage. */
export async function adminFetch<T>(
  path: string,
  method: Method = "GET",
  data: unknown = null,
): Promise<T> {
  const session = await readSession();
  if (!session) redirect("/login");
  try {
    return await bridgeFetch<T>(path, method, data, session);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect("/login?expired=1");
    }
    throw error;
  }
}
