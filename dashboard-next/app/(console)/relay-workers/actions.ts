"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SLUG = /^[a-z][a-z0-9-]{2,63}$/;

function positiveInt(value: FormDataEntryValue | null): number {
  const text = String(value ?? "");
  return /^[1-9][0-9]*$/.test(text) ? Number(text) : 0;
}

/** Show only approved error identifiers; never a provider error body. */
function fail(error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.code === "reauthentication_required" || error.status === 428) redirect("/relay-workers?error=reauth");
  const known = new Set([
    "invalid_relay_worker", "relay_worker_exists", "configuration_changed",
    "transport_endpoint_not_approved", "relay_worker_not_verified",
    "relay_worker_not_found", "bot_state_unchanged", "invalid_credentials",
    "invalid_verification", "relay_pool_disabled",
  ]);
  redirect(`/relay-workers?error=${error.code && known.has(error.code) ? error.code : "save"}`);
}

/** Create an inert Worker only from a deployment-allowlisted HTTPS origin. */
export async function createRelayWorker(form: FormData): Promise<void> {
  const slug = String(form.get("slug") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  const origin = String(form.get("origin") ?? "").trim();
  const max_rps = positiveInt(form.get("max_rps"));
  const max_inflight = positiveInt(form.get("max_inflight"));
  if (!SLUG.test(slug) || name.length < 1 || name.length > 160 ||
    origin.length < 8 || origin.length > 300 ||
    max_rps < 1 || max_rps > 20 || max_inflight < 1 || max_inflight > 50) {
    redirect("/relay-workers?error=validation");
  }
  try {
    await adminFetch("/relay-workers", "POST", {
      slug, name, origin, max_rps, max_inflight,
    });
  } catch (error) { fail(error); }
  revalidatePath("/relay-workers");
  redirect("/relay-workers?saved=created");
}

/** Pause or resume a verified Worker with fresh MFA and optimistic locking. */
export async function setRelayWorkerState(form: FormData): Promise<void> {
  const id = String(form.get("worker_id") ?? "");
  const state = String(form.get("state") ?? "");
  const expected_version = positiveInt(form.get("expected_version"));
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!UUID.test(id) || !["active", "paused", "disabled"].includes(state) ||
    !expected_version || !current_password || current_password.length > 256 ||
    !/^[0-9]{6}$/.test(second_factor)) {
    redirect("/relay-workers?error=validation");
  }
  try {
    await adminFetch(`/relay-workers/${id}/state`, "POST", {
      expected_version, state, current_password, second_factor,
    });
  } catch (error) { fail(error); }
  revalidatePath("/relay-workers");
  redirect("/relay-workers?saved=state");
}
