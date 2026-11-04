"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";
import type { CustomerMenuAction } from "@/lib/customer-experience";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MENU: CustomerMenuAction[] = [
  "shop", "search", "cart", "orders", "account", "support",
];

function target(form: FormData): { scope: "store" | "bot"; id: string; url: string } {
  const scope = String(form.get("scope") ?? "");
  const id = String(form.get("target_id") ?? "");
  if ((scope !== "store" && scope !== "bot") || !UUID.test(id)) {
    redirect("/bots?error=validation");
  }
  return {
    scope,
    id,
    url: scope === "store" ? "/stores" : `/bots/${id}`,
  };
}

function proof(form: FormData): {
  current_password: string; second_factor: string;
} {
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!current_password || current_password.length > 256 ||
    !/^[0-9]{6}$/.test(second_factor)) {
    redirect("/account?error=reauth");
  }
  return { current_password, second_factor };
}

function failure(error: unknown, destination: string): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  const known = new Set([
    "configuration_changed", "invalid_menu_policy",
    "invalid_checkout_policy", "checkout_terms_required",
    "store_permission_denied", "store_access_denied",
    "invalid_credentials", "invalid_verification",
  ]);
  const code = error.code && known.has(error.code)
    ? error.code : "save";
  redirect(`${destination}?ux_error=${code}`);
}

/** Safe menu ordering, never arbitrary callback URLs or provider methods. */
export async function saveCustomerMenu(form: FormData): Promise<void> {
  const selection = target(form);
  const version = Number(form.get("expected_version"));
  const selected = form.getAll("menu_action").map(String);
  if (!Number.isSafeInteger(version) || version < 0 ||
      !selected.includes("shop") ||
      selected.length !== new Set(selected).size ||
      selected.length > MENU.length ||
      selected.some((item) => !MENU.includes(item as CustomerMenuAction))) {
    redirect(`${selection.url}?ux_error=validation`);
  }
  const actions = selected.sort((left, right) => {
    const a = Number(form.get(`order:${left}`) ?? 100);
    const b = Number(form.get(`order:${right}`) ?? 100);
    return a - b;
  });
  const prefix = selection.scope === "store"
    ? `/stores/${selection.id}/customer-menu`
    : `/bot-registry/${selection.id}/customer-menu`;
  try {
    await adminFetch(prefix, "POST", {
      expected_version: version, actions, ...proof(form),
    });
  } catch (error) { failure(error, selection.url); }
  revalidatePath(selection.url);
  redirect(`${selection.url}?ux_saved=menu`);
}

/** Explicitly choose Manual or Instant checkout with Store-owned terms. */
export async function saveCheckoutPolicy(form: FormData): Promise<void> {
  const selection = target(form);
  const expected_version = Number(form.get("expected_version"));
  const mode = String(form.get("mode") ?? "");
  if (!Number.isSafeInteger(expected_version) ||
    expected_version < 0 || !["manual", "instant", "inherit"].includes(mode)) {
    redirect(`${selection.url}?ux_error=validation`);
  }
  const prefix = selection.scope === "store"
    ? `/stores/${selection.id}/checkout-policy`
    : `/bot-registry/${selection.id}/checkout-policy`;
  const terms_version = String(form.get("terms_version") ?? "").trim();
  const terms_text = String(form.get("terms_text") ?? "").trim();
  if (selection.scope === "store" && (mode === "inherit" ||
      terms_version.length < 1 || terms_version.length > 32 ||
      terms_text.length > 6000)) {
    redirect(`${selection.url}?ux_error=validation`);
  }
  const payload = selection.scope === "store"
    ? {
      expected_version,
      mode,
      terms_version,
      terms_text,
      ...proof(form),
    }
    : {
      expected_version,
      mode_override: mode === "inherit" ? null : mode,
      ...proof(form),
    };
  if (selection.scope === "store" && mode === "inherit") {
    redirect(`${selection.url}?ux_error=validation`);
  }
  try {
    await adminFetch(prefix, "POST", payload);
  } catch (error) { failure(error, selection.url); }
  revalidatePath(selection.url);
  redirect(`${selection.url}?ux_saved=checkout`);
}
