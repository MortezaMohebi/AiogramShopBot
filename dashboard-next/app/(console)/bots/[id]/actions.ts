"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const STATUSES = new Set(["active", "maintenance", "paused", "disabled"]);
const ENVIRONMENTS = new Set(["staging", "codespaces", "production"]);
const SAFE_ERRORS = new Set([
  "bot_runtime_not_ready", "configuration_changed", "duplicate_provider_bot",
  "duplicate_bot_credential", "bot_identity_mismatch", "invalid_bot_token_format",
  "invalid_support_url", "invalid_credential_state", "bot_state_reason_required",
  "bot_state_unchanged", "provider_state_unavailable", "bot_secret_key_unavailable",
  "bot_secret_unreadable", "legacy_bot_credential_locked", "mfa_enrollment_required",
  "bot_credential_stage_requires_draft", "permission_denied",
  "invalid_receiver_mode", "receiver_worker_unavailable",
  "receiver_lease_lost", "multibot_runtime_disabled",
  "bot_credential_not_verified", "receiver_change_in_progress",
  "webhook_url_invalid", "webhook_owned_elsewhere",
  "receiver_needs_review", "invalid_operation_state",
]);

/** Do not permit arbitrary URL paths to be constructed from form content. */
function idFrom(form: FormData): string {
  const id = String(form.get("id") ?? "");
  if (!UUID.test(id)) redirect("/bots?error=validation");
  return id;
}
function failure(error: unknown, id: string): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.status === 428) redirect(`/bots/${id}?error=reauth`);
  const code = error.code && SAFE_ERRORS.has(error.code)
    ? error.code : "save";
  redirect(`/bots/${id}?error=${code}`);
}
function positiveInt(value: FormDataEntryValue | null): number | null {
  const text = String(value ?? "");
  return /^[1-9][0-9]*$/.test(text) ? Number(text) : null;
}

/** Save public copy and operator assignment without touching credentials. */
export async function saveBotDetails(form: FormData): Promise<void> {
  const id = idFrom(form);
  const expected_version = positiveInt(form.get("expected_version"));
  const name = String(form.get("name") ?? "").trim();
  const environment = String(form.get("environment") ?? "");
  const owner = String(form.get("owner_staff_id") ?? "");
  const welcome_message = String(form.get("welcome_message") ?? "").trim();
  const maintenance_message = String(form.get("maintenance_message") ?? "").trim();
  const support_url = String(form.get("support_url") ?? "").trim();
  if (
    !expected_version || !name || name.length > 160 ||
    !ENVIRONMENTS.has(environment) ||
    (owner && !positiveInt(form.get("owner_staff_id"))) ||
    welcome_message.length > 4096 || maintenance_message.length > 4096 ||
    support_url.length > 500
  ) redirect(`/bots/${id}?error=validation`);
  try {
    await adminFetch(`/bot-registry/${id}/settings`, "PATCH", {
      expected_version, name,
      owner_staff_id: owner ? Number(owner) : null,
      environment,
      welcome_message: welcome_message || null,
      maintenance_message: maintenance_message || null,
      support_url,
    });
  } catch (error) { failure(error, id); }
  revalidatePath("/bots");
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=settings`);
}

/** Immediately restrict legacy commerce; retain all pending payment receipts. */
export async function changeBotState(form: FormData): Promise<void> {
  const id = idFrom(form);
  const expected_version = positiveInt(form.get("expected_version"));
  const state = String(form.get("state") ?? "");
  const reason = String(form.get("reason") ?? "").trim();
  if (!expected_version || !STATUSES.has(state) ||
      reason.length > 500 ||
      (["paused", "disabled"].includes(state) && reason.length < 8)) {
    redirect(`/bots/${id}?error=validation`);
  }
  try {
    await adminFetch(`/bot-registry/${id}/state`, "POST", {
      expected_version, state, reason,
    });
  } catch (error) { failure(error, id); }
  revalidatePath("/bots");
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=state`);
}

/** Encrypt a proposed credential in PostgreSQL without ever activating it. */
export async function stageBotCredential(form: FormData): Promise<void> {
  const id = idFrom(form);
  const token = String(form.get("token") ?? "").trim();
  if (!token || token.length < 24 || token.length > 512) {
    redirect(`/bots/${id}?error=validation`);
  }
  try {
    await adminFetch(`/bot-registry/${id}/credentials/stage`, "POST", {
      token,
    });
  } catch (error) { failure(error, id); }
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=staged`);
}

/** Verify exactly the selected staged token, or legacy active credential. */
export async function verifyBotCredential(form: FormData): Promise<void> {
  const id = idFrom(form);
  const version = positiveInt(form.get("version"));
  try {
    await adminFetch(`/bot-registry/${id}/verify`, "POST", {
      version,
    });
  } catch (error) { failure(error, id); }
  revalidatePath("/bots");
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=verified`);
}

/** Save a bot's isolated receiver config without sending provider requests. */
export async function stageBotReceiver(form: FormData): Promise<void> {
  const id = idFrom(form);
  const mode = String(form.get("mode") ?? "");
  if (mode !== "webhook" && mode !== "polling") {
    redirect(`/bots/${id}?error=validation`);
  }
  try {
    await adminFetch(`/bot-registry/${id}/receiver/stage`, "POST", { mode });
  } catch (error) { failure(error, id); }
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=receiver_staged`);
}

/** Activate an opted-in receiver with fresh password and MFA verification. */
export async function activateBotReceiver(form: FormData): Promise<void> {
  const id = idFrom(form);
  const expected_version = positiveInt(form.get("expected_version"));
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!expected_version || !current_password || current_password.length > 256 ||
      !/^[0-9]{6}$/.test(second_factor)) {
    redirect(`/bots/${id}?error=validation`);
  }
  try {
    // Provider checks may exceed a read timeout; mutations are never retried.
    await adminFetch(`/bot-registry/${id}/receiver/activate`, "POST", {
      expected_version, current_password, second_factor,
    }, 90_000);
  } catch (error) { failure(error, id); }
  revalidatePath("/bots");
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=receiver_active`);
}

/** Revoke a proposed token; the active legacy Token stays untouched. */
export async function revokeBotCredential(form: FormData): Promise<void> {
  const id = idFrom(form);
  const version = positiveInt(form.get("version"));
  if (!version) redirect(`/bots/${id}?error=validation`);
  try {
    await adminFetch(`/bot-registry/${id}/credentials/revoke`, "POST", {
      version,
    });
  } catch (error) { failure(error, id); }
  revalidatePath(`/bots/${id}`);
  redirect(`/bots/${id}?saved=revoked`);
}
