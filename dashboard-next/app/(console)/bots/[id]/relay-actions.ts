"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ERRORS = new Set([
  "configuration_changed", "invalid_relay_priority",
  "relay_priority_taken",
  "relay_route_not_supported", "relay_route_must_pause",
  "duplicate_relay_credential", "invalid_worker_secret",
  "relay_pool_disabled", "relay_activation_not_ready",
  "relay_probe_failed", "bot_identity_mismatch",
  "transport_endpoint_not_approved", "invalid_credential_state",
  "relay_worker_not_found", "invalid_operation_state",
]);

function id(form: FormData, key: string): string {
  const value = String(form.get(key) ?? "");
  if (!UUID.test(value)) redirect("/bots?error=validation");
  return value;
}

function int(form: FormData, key: string): number {
  const value = String(form.get(key) ?? "");
  return /^[1-9][0-9]*$/.test(value) ? Number(value) : 0;
}

function fail(error: unknown, botId: string): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.code === "reauthentication_required" || error.status === 428) redirect(`/bots/${botId}?relay_error=reauth`);
  redirect(`/bots/${botId}?relay_error=${
    error.code && ERRORS.has(error.code) ? error.code : "save"
  }`);
}

function done(botId: string, action: string): never {
  revalidatePath("/relay-workers");
  revalidatePath(`/bots/${botId}`);
  redirect(`/bots/${botId}?relay_saved=${action}`);
}

function proof(form: FormData): { current_password: string; second_factor: string } {
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!current_password || current_password.length > 256 ||
    !/^[0-9]{6}$/.test(second_factor)) {
    redirect("/bots?error=validation");
  }
  return { current_password, second_factor };
}

/** Stage a Many2many assignment without sending a provider request. */
export async function assignRelayRoute(form: FormData): Promise<void> {
  const botId = id(form, "bot_id");
  const worker_id = id(form, "worker_id");
  const priority = int(form, "priority");
  const expected_version = int(form, "expected_version") || null;
  if (priority < 1 || priority > 1000) redirect(`/bots/${botId}?relay_error=validation`);
  try {
    await adminFetch(`/bot-registry/${botId}/relay-routes`, "POST", {
      worker_id, priority, expected_version,
    });
  } catch (error) { fail(error, botId); }
  done(botId, "assigned");
}

/** Record an independent Worker secret; never expose it again in the UI. */
export async function stageRelayCredential(form: FormData): Promise<void> {
  const botId = id(form, "bot_id");
  const workerId = id(form, "worker_id");
  const secret = String(form.get("secret") ?? "");
  if (secret.length < 32 || secret.length > 256) {
    redirect(`/bots/${botId}?relay_error=validation`);
  }
  try {
    await adminFetch(
      `/bot-registry/${botId}/relay-routes/${workerId}/credentials/stage`,
      "POST", { secret },
    );
  } catch (error) { fail(error, botId); }
  done(botId, "staged");
}

/** Probe the Worker without creating an invoice, message or webhook. */
export async function activateRelayRoute(form: FormData): Promise<void> {
  const botId = id(form, "bot_id");
  const workerId = id(form, "worker_id");
  const expected_version = int(form, "expected_version");
  const credential_version = int(form, "credential_version");
  if (!expected_version || !credential_version) {
    redirect(`/bots/${botId}?relay_error=validation`);
  }
  try {
    await adminFetch(`/bot-registry/${botId}/relay-routes/${workerId}/activate`,
      "POST", { expected_version, credential_version, ...proof(form) }, 45_000);
  } catch (error) { fail(error, botId); }
  done(botId, "activated");
}

/** Stop new route selection without retrying prior ambiguous sends. */
export async function pauseRelayRoute(form: FormData): Promise<void> {
  const botId = id(form, "bot_id");
  const workerId = id(form, "worker_id");
  const expected_version = int(form, "expected_version");
  if (!expected_version) redirect(`/bots/${botId}?relay_error=validation`);
  try {
    await adminFetch(`/bot-registry/${botId}/relay-routes/${workerId}/pause`,
      "POST", { expected_version, ...proof(form) });
  } catch (error) { fail(error, botId); }
  done(botId, "paused");
}

/** Revoke only inactive keys after removing them from the Worker secret JSON. */
export async function revokeRelayCredential(form: FormData): Promise<void> {
  const botId = id(form, "bot_id");
  const workerId = id(form, "worker_id");
  const version = int(form, "version");
  if (!version) redirect(`/bots/${botId}?relay_error=validation`);
  try {
    await adminFetch(
      `/bot-registry/${botId}/relay-routes/${workerId}/credentials/revoke`,
      "POST", { version, ...proof(form) },
    );
  } catch (error) { fail(error, botId); }
  done(botId, "revoked");
}
