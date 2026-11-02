import "server-only";

import { createHash, createHmac } from "node:crypto";
import { redirect } from "next/navigation";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

interface Identity {
  id: number;
  version: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
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

/** Sign the EXACT outgoing bytes; binary and JSON share the same HMAC policy. */
export async function bridgeResponse(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  body: Uint8Array | string | null,
  contentType: string | null,
  identity: Identity | null,
  timeoutMs = 15_000,
): Promise<Response> {
  const { host, secret } = environment();
  if (!path.startsWith("/") || path.startsWith("//")) {
    throw new Error("Invalid internal API path.");
  }
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

  const response = await fetch(url, {
    method,
    headers: {
      ...(contentType ? { "content-type": contentType } : {}),
      "x-shop-time": timestamp,
      "x-shop-signature": signature,
      "x-shop-staff": staff,
      "x-shop-version": version,
    },
    // Request bytes must remain byte-for-byte identical after signing.
    body: method === "GET" || body === null ? undefined : new Uint8Array(bytes),
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(timeoutMs),
  });

  if (!response.ok) {
    let detail = `API error ${response.status}`;
    try {
      const result: unknown = await response.json();
      if (
        typeof result === "object" && result !== null &&
        "detail" in result && typeof result.detail === "string"
      ) {
        detail = result.detail;
      }
    } catch {
      // No stack traces, HTML bodies, cookies or provider details reach the UI.
    }
    throw new ApiError(response.status, detail);
  }
  return response;
}

/** Strictly JSON-only convenience wrapper for ordinary server actions. */
export async function bridgeFetch<T>(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE",
  data: unknown,
  identity: Identity | null,
): Promise<T> {
  const raw = method === "GET" || method === "DELETE"
    ? null
    : JSON.stringify(data ?? {});
  const response = await bridgeResponse(
    path, method, raw, raw === null ? null : "application/json", identity,
  );
  return (await response.json()) as T;
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

/** Role-sensitive backend call; Python rechecks staff against PostgreSQL. */
export async function adminFetch<T>(
  path: string,
  method: "GET" | "POST" | "PATCH" | "DELETE" = "GET",
  data: unknown = null,
): Promise<T> {
  const session = await readSession();
  if (!session) redirect("/login");
  return bridgeFetch<T>(path, method, data, session);
}
