"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const RAILS = new Set(["bale_wallet", "telegram_fiat", "telegram_stars"]);

function failure(error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.code === "reauthentication_required" || error.status === 428) redirect("/payment-accounts?error=reauth");
  const codes = new Set([
    "configuration_changed", "payment_account_invalid", "payment_token_invalid",
    "payment_token_not_supported", "payment_account_not_found",
    "bot_state_unchanged", "payment_access_store_mismatch",
    "invalid_credentials", "invalid_verification",
    "telegram_fiat_unavailable",
  ]);
  redirect(`/payment-accounts?error=${error.code && codes.has(error.code) ? error.code : "save"}`);
}

function proof(form: FormData): { current_password: string } {
  const current_password = String(form.get("current_password") ?? "");

  if (!current_password || current_password.length > 256) {
    redirect("/payment-accounts?error=validation");
  }
  return { current_password };
}

/** Store secrets server-side; do not activate or grant any bot automatically. */
export async function createPaymentAccount(form: FormData): Promise<void> {
  const store_id = String(form.get("store_id") ?? "");
  const platform = String(form.get("platform") ?? "");
  const rail_type = String(form.get("rail_type") ?? "");
  const name = String(form.get("name") ?? "").trim();
  const token = String(form.get("token") ?? "");
  if (!UUID.test(store_id) || !["telegram", "bale"].includes(platform) ||
      !RAILS.has(rail_type) || !name || name.length > 100 ||
      (rail_type !== "telegram_stars" && (token.length < 20 || token.length > 512)) ||
      (rail_type === "telegram_stars" && Boolean(token))) {
    redirect("/payment-accounts?error=validation");
  }
  try {
    await adminFetch(`/stores/${store_id}/payment-accounts`, "POST", {
      platform, rail_type, name, token: token || null, ...proof(form),
    });
  } catch (error) { failure(error); }
  revalidatePath("/payment-accounts");
  redirect("/payment-accounts?saved=created");
}

/** A Provider account state change cannot rewrite paid order history. */
export async function setPaymentAccountState(form: FormData): Promise<void> {
  const id = String(form.get("account_id") ?? "");
  const expected_version = Number(form.get("expected_version"));
  const state = String(form.get("state") ?? "");
  if (!UUID.test(id) || !Number.isSafeInteger(expected_version) ||
      expected_version <= 0 || !["active", "disabled"].includes(state)) {
    redirect("/payment-accounts?error=validation");
  }
  try {
    await adminFetch(`/payment-accounts/${id}/state`, "POST", {
      expected_version, state, ...proof(form),
    });
  } catch (error) { failure(error); }
  revalidatePath("/payment-accounts");
  redirect("/payment-accounts?saved=state");
}
