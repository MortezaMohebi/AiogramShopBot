"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function safeFailure(error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.code === "reauthentication_required" || error.status === 428) redirect("/stores?error=reauth");
  const allowed = new Set([
    "configuration_changed", "identity_credit_requires_reconciliation",
    "invalid_store_sharing_policy", "invalid_credentials",
    "invalid_verification", "permission_denied",
  ]);
  redirect(`/stores?error=${error.code && allowed.has(error.code) ? error.code : "save"}`);
}

/** Switch sharing only with fresh MFA and no untransferred wallet balances. */
export async function saveStoreCommercePolicy(form: FormData): Promise<void> {
  const storeId = String(form.get("store_id") ?? "");
  const version = Number(form.get("expected_version"));
  const cart_scope = String(form.get("cart_scope") ?? "");
  const credit_scope = String(form.get("credit_scope") ?? "");
  const current_password = String(form.get("current_password") ?? "");

  if (!UUID.test(storeId) || !Number.isSafeInteger(version) || version < 0 ||
      !["bot", "customer"].includes(cart_scope) ||
      !["identity", "customer"].includes(credit_scope) ||
      !current_password || current_password.length > 256) {
    redirect("/stores?error=validation");
  }
  try {
    await adminFetch(`/stores/${storeId}/commerce`, "POST", {
      expected_version: version, cart_scope, credit_scope,
      current_password,
    });
  } catch (error) { safeFailure(error); }
  revalidatePath("/stores");
  redirect("/stores?saved=policy");
}
