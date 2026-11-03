"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const platformSet = new Set(["telegram", "bale"]);
const validUpdates = new Set([
  "message", "callback_query", "pre_checkout_query",
  "edited_message", "my_chat_member",
]);

/** Accept only a supported platform and approved update options. */
export async function saveBotProfile(form: FormData): Promise<void> {
  const platform = String(form.get("platform") ?? "");
  const display_name = String(form.get("display_name") ?? "").trim();
  const owner = String(form.get("owner_staff_id") ?? "");
  const environment = String(form.get("environment") ?? "staging");
  const request_timeout_seconds = Number(form.get("request_timeout_seconds"));
  const poll_timeout_seconds = Number(form.get("poll_timeout_seconds"));
  const allowed_updates = form.getAll("allowed_updates").map(String);
  if (!platformSet.has(platform) || display_name.length > 120 ||
      (owner && !/^[1-9][0-9]*$/.test(owner)) ||
      !["codespaces", "staging", "production"].includes(environment) ||
      !Number.isSafeInteger(request_timeout_seconds) ||
      request_timeout_seconds < 5 || request_timeout_seconds > 60 ||
      !Number.isSafeInteger(poll_timeout_seconds) ||
      poll_timeout_seconds < 0 || poll_timeout_seconds > 30 ||
      allowed_updates.some(item => !validUpdates.has(item)) ||
      new Set(allowed_updates).size !== allowed_updates.length) {
    redirect("/bot-connections?error=validation");
  }
  try {
    await adminFetch(`/bot-profiles/${platform}`, "POST", {
      display_name,
      owner_staff_id: owner ? Number(owner) : null,
      environment,
      maintenance_enabled: form.has("maintenance_enabled"),
      request_timeout_seconds,
      poll_timeout_seconds,
      allowed_updates,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    redirect(`/bot-connections?error=${error.status === 428 ? "reauth" : "save"}`);
  }
  revalidatePath("/bot-connections");
  redirect("/bot-connections?saved=1");
}

/** Probe the actual configured token's identity; never accept a token here. */
export async function verifyBotProfile(form: FormData): Promise<void> {
  const platform = String(form.get("platform") ?? "");
  if (!platformSet.has(platform)) redirect("/bot-connections?error=validation");
  try {
    await adminFetch(`/bot-profiles/${platform}/verify`, "POST", {});
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    redirect(`/bot-connections?error=${error.status === 409 ? "identity" :
      error.status === 428 ? "reauth" : "probe"}`);
  }
  revalidatePath("/bot-connections");
  redirect("/bot-connections?verified=1");
}
