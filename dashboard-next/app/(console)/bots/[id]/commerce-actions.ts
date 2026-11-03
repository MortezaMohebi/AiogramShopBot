"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function ids(form: FormData): string {
  const value = String(form.get("bot_id") ?? "");
  if (!UUID.test(value)) redirect("/bots?error=validation");
  return value;
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

function failure(error: unknown, botId: string): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.status === 428) redirect(`/bots/${botId}?commerce_error=reauth`);
  const codes = new Set([
    "configuration_changed", "invalid_bot_commerce_policy",
    "payment_access_store_mismatch", "payment_access_invalid",
    "payment_account_not_active", "invalid_credentials", "invalid_verification",
  ]);
  redirect(`/bots/${botId}?commerce_error=${
    error.code && codes.has(error.code) ? error.code : "save"
  }`);
}

/** Explicitly allow/deny Cart and internal credit for the selected bot. */
export async function saveBotCommercePolicy(form: FormData): Promise<void> {
  const botId = ids(form);
  const expected_version = Number(form.get("expected_version"));
  const cart_enabled = String(form.get("cart_enabled") ?? "");
  const credit_enabled = String(form.get("credit_enabled") ?? "");
  const credit_label = String(form.get("credit_label") ?? "").trim();
  if (!Number.isSafeInteger(expected_version) || expected_version < 0 ||
    !["inherit", "true", "false"].includes(cart_enabled) ||
    !["inherit", "true", "false"].includes(credit_enabled) ||
    credit_label.length > 80) {
    redirect(`/bots/${botId}?commerce_error=validation`);
  }
  const truth = (value: string): boolean | null =>
    value === "inherit" ? null : value === "true";
  try {
    await adminFetch(`/bot-registry/${botId}/commerce`, "POST", {
      expected_version,
      cart_enabled: truth(cart_enabled),
      credit_enabled: truth(credit_enabled),
      credit_label: credit_label || null,
      ...proof(form),
    });
  } catch (error) { failure(error, botId); }
  revalidatePath(`/bots/${botId}`);
  redirect(`/bots/${botId}?commerce_saved=policy`);
}

/** Grant a Store-owned Provider only to a matching-platform bot. */
export async function setBotPaymentAccess(form: FormData): Promise<void> {
  const botId = ids(form);
  const accountId = String(form.get("account_id") ?? "");
  const enabled = String(form.get("enabled") ?? "") === "true";
  const priority = Number(form.get("priority"));
  if (!UUID.test(accountId) || !Number.isSafeInteger(priority) ||
      priority < 1 || priority > 1000) {
    redirect(`/bots/${botId}?commerce_error=validation`);
  }
  try {
    await adminFetch(
      `/bot-registry/${botId}/payment-accounts/${accountId}/grant`,
      "POST", { enabled, priority, ...proof(form) },
    );
  } catch (error) { failure(error, botId); }
  revalidatePath(`/bots/${botId}`);
  redirect(`/bots/${botId}?commerce_saved=access`);
}
