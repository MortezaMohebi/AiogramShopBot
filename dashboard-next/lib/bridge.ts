import "server-only";
import { createHash, createHmac, randomUUID } from "node:crypto";
import { redirect } from "next/navigation";
import { readSession } from "@/lib/session";
import type { Staff } from "@/lib/types";

interface Identity { id: number; version: number; sid?: string }
type Method = "GET" | "POST" | "PATCH" | "DELETE";
const SAFE_CODES = new Set([
  "session_expired", "permission_denied", "reauthentication_required", "invalid_credentials",
  "mfa_required", "invalid_verification", "mfa_not_configured", "mfa_unavailable",
  "mfa_already_enabled", "mfa_enrollment_expired", "password_unchanged", "invalid_timezone",
  "invalid_request", "session_not_found", "temporarily_locked", "security_service_unavailable",
  "operation_not_found", "invalid_operation_state", "idempotency_conflict",
  "connection_change_in_progress", "configuration_changed", "legacy_endpoint_retired",
  "connection_worker_unavailable", "reconciliation_required",
  "invitation_only", "invalid_link", "password_policy_failed", "mfa_enrollment_required",
  "mfa_required_by_role", "invitation_not_found", "staff_username_exists",
  "staff_not_found", "last_admin_protected", "use_my_account",
  "username_unchanged", "customer_not_found", "restriction_reason_required",
  "invalid_transport_mode", "invalid_proxy_endpoint", "invalid_proxy_credentials",
  "invalid_worker_origin", "invalid_worker_secret",
  "transport_endpoint_not_approved", "transport_config_unreadable",
  "transport_probe_failed", "transport_reconciliation_required",
  "transport_worker_unavailable", "transport_stage_expired",
  "transport_unchanged", "transport_history_not_found",
  "transport_interrupted", "transport_restored_to_verified",
  "bot_identity_mismatch", "provider_not_configured", "provider_state_unavailable",
  "invalid_registry_slug", "invalid_registry_name", "store_slug_exists",
  "store_not_found", "store_not_active", "bot_slug_exists",
  "bot_not_found", "bot_not_active", "invalid_bot_platform",
  "legacy_bot_credential_locked", "bot_credential_stage_requires_draft",
  "invalid_bot_token_format", "invalid_credential_state",
  "bot_secret_key_invalid", "bot_secret_key_unavailable",
  "bot_secret_unreadable", "bot_secret_binding_mismatch",
  "bot_secret_unavailable", "bot_credential_missing",
  "credential_version_conflict", "invalid_bot_runtime",
  "invalid_bot_state", "bot_state_reason_required", "bot_state_unchanged",
  "bot_runtime_not_ready", "duplicate_provider_bot", "duplicate_bot_credential",
  "invalid_support_url", "use_bot_registry",
  "invalid_catalog_rule", "catalog_target_not_found",
  "catalog_store_not_ready",




  "invalid_receiver_mode", "receiver_worker_unavailable",
  "receiver_lease_lost", "multibot_runtime_disabled",
  "bot_credential_not_verified", "receiver_change_in_progress",
  "webhook_url_invalid", "webhook_owned_elsewhere",
  "receiver_needs_review", "receiver_capacity_reached",
  "provider_outcome_unknown",
  "invalid_relay_worker", "relay_worker_exists",
  "relay_worker_not_found", "relay_worker_not_verified",
  "relay_route_not_supported", "invalid_relay_priority",
  "relay_priority_taken",
  "relay_route_must_pause", "relay_activation_not_ready",
  "relay_pool_disabled", "relay_probe_failed",
  "relay_route_unavailable", "relay_secret_unreadable",
  "relay_secret_binding_mismatch", "duplicate_relay_credential",
  "invalid_uom", "uom_already_exists", "uom_category_not_found",
  "uom_not_available", "uom_category_mismatch", "uom_locked",
  "uom_in_use", "unknown_model", "unknown_model_field",
  "invalid_model_filter", "invalid_model_operator",
  "invalid_model_pagination", "invalid_model_group",
  "unsupported_data_format", "model_export_too_large",
  "model_import_not_supported", "invalid_import_file",
  "invalid_import_columns", "import_too_many_rows",
  "import_formula_not_allowed", "import_identity_required",
  "import_duplicate_key", "import_conflict",
  "import_identity_conflict", "import_required_field",
  "import_stock_adjustment_required", "import_publish_requires_review",
  "import_preview_required", "import_data_changed",
  "invalid_import_value",
  "invalid_external_reference", "import_empty_file",
  "invalid_import_request",
  "confirmation_required",
]);
export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly requestId?: string, readonly code?: string) {
    super(message); this.name = "ApiError";
  }
}
/** Log metadata only: never URL queries, bodies, session bearers or provider errors. */
function bridgeFailure(path: string, method: Method, status: number,
  code: "configuration" | "network" | "timeout" | "http" | "invalid_json",
  requestId = randomUUID(), safeCode?: string): ApiError {
  const route = path.split("?", 1)[0].replace(/\/[0-9]+(?=\/|$)/g, "/:id").slice(0, 160);
  console.warn("[shop-admin/bridge]", { requestId, method, route, status, code });
  return new ApiError(status, `Administrative API ${code} (${requestId})`, requestId, safeCode);
}
function environment(): { host: URL; secret: string } {
  const host = process.env.SHOP_FASTAPI_INTERNAL_URL, secret = process.env.NEXT_ADMIN_BRIDGE_SECRET ?? "";
  if (!host || secret.length < 32) throw new Error("Bridge configuration missing");
  const origin = new URL(host);
  if (!["http:", "https:"].includes(origin.protocol)) throw new Error("Unsupported bridge scheme");
  return { host: origin, secret };
}
/** Sign exact bytes and bind the backend session to this request; never auto-retry writes. */
export async function bridgeResponse(path: string, method: Method, body: Uint8Array | string | null,
  contentType: string | null, identity: Identity | null, timeoutMs = 15_000): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Invalid internal API path.");
  let connection: ReturnType<typeof environment>;
  try { connection = environment(); }
  catch { throw bridgeFailure(`/internal/admin/v1${path}`, method, 503, "configuration"); }
  const { host, secret } = connection;
  const url = new URL(`/internal/admin/v1${path}`, host);
  if (!url.pathname.startsWith("/internal/admin/v1/")) throw new Error("Invalid internal admin route.");
  const bytes = typeof body === "string" ? Buffer.from(body, "utf8") : body === null ? new Uint8Array() : body;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const target = url.pathname + url.search, digest = createHash("sha256").update(bytes).digest("hex");
  const staff = String(identity?.id ?? 0), version = String(identity?.version ?? 0);
  const signature = createHmac("sha256", secret).update([timestamp, method, target, digest, staff, version].join("\n")).digest("hex");
  const requestId = randomUUID(), signal = AbortSignal.timeout(timeoutMs);
  const sessionHeaders: Record<string, string> = identity?.sid ? {
    "x-shop-session": identity.sid,
    "x-shop-session-proof": createHmac("sha256", secret).update(`session-v1\n${signature}\n${identity.sid}`).digest("hex"),
  } : {};
  let response: Response;
  try {
    response = await fetch(url, {
      method, headers: { ...(contentType ? { "content-type": contentType } : {}),
        "x-shop-time": timestamp, "x-shop-signature": signature, "x-shop-staff": staff,
        "x-shop-version": version, "x-shop-request-id": requestId, ...sessionHeaders },
      body: method === "GET" || body === null ? undefined : new Uint8Array(bytes),
      cache: "no-store", redirect: "error", signal,
    });
  } catch {
    throw bridgeFailure(url.pathname, method, signal.aborted ? 504 : 503, signal.aborted ? "timeout" : "network", requestId);
  }
  if (!response.ok) {
    // Accept only short known error codes, never arbitrary FastAPI/provider text.
    let safeCode: string | undefined;
    const reader = response.body?.getReader();
    if (reader) {
      try {
        const parts: Uint8Array[] = []; let size = 0;
        while (size <= 4096) {
          const { done, value } = await reader.read(); if (done) break;
          size += value.byteLength; if (size > 4096) break; parts.push(value);
        }
        if (size <= 4096) {
          const data: unknown = JSON.parse(Buffer.concat(parts).toString("utf8"));
          if (data && typeof data === "object" && "detail" in data && typeof data.detail === "string" && SAFE_CODES.has(data.detail)) safeCode = data.detail;
        }
      } catch { /* Arbitrary HTML/traceback is discarded. */ }
      finally { await reader.cancel().catch(() => undefined); reader.releaseLock(); }
    }
    throw bridgeFailure(url.pathname, method, response.status, "http", requestId, safeCode);
  }
  return response;
}
export async function bridgeFetch<T>(path: string, method: Method, data: unknown,
  identity: Identity | null, timeoutMs = 15_000): Promise<T> {
  const raw = method === "GET" || method === "DELETE" ? null : JSON.stringify(data ?? {});
  const response = await bridgeResponse(path, method, raw, raw === null ? null : "application/json", identity, timeoutMs);
  try { return await response.json() as T; }
  catch { throw bridgeFailure(`/internal/admin/v1${path}`, method, 502, "invalid_json"); }
}
export async function currentStaff(): Promise<Staff> {
  const session = await readSession(); if (!session) redirect("/login");
  try { return await bridgeFetch<Staff>("/auth/me", "GET", null, session); }
  catch (error) { if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1"); throw error; }
}
export async function adminFetch<T>(
  path: string, method: Method = "GET", data: unknown = null,
  timeoutMs = 15_000,
): Promise<T> {
  const session = await readSession(); if (!session) redirect("/login");
  try { return await bridgeFetch<T>(path, method, data, session, timeoutMs); }
  catch (error) { if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1"); throw error; }
}
