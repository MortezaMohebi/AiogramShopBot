"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Modify only future merchant-funded referral rewards; never wallet balances. */
export async function saveReferralPolicy(form: FormData) {
  const percent = String(form.get("percent") ?? "0").trim();
  const minimum = String(form.get("min_order_irr") ?? "0").trim();
  const maximum = String(form.get("max_bonus_irr") ?? "0").trim();
  if (![percent, minimum, maximum].every((value) => /^\d{1,12}$/.test(value))) {
    redirect("/settings?error=referral");
  }
  let failed = false;
  try {
    await adminFetch("/referral-policy", "PATCH", {
      is_enabled: form.has("is_enabled"),
      percent: Number(percent),
      min_order_irr: Number(minimum),
      max_bonus_irr: Number(maximum),
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/settings?error=referral");
  revalidatePath("/settings");
  redirect("/settings?saved=referral");
}

/** Persist the installation name and accent chosen by the administrator. */
export async function savePwaAppearance(form: FormData) {
  const name = String(form.get("name") ?? "").trim();
  const shortName = String(form.get("short_name") ?? "").trim();
  const color = String(form.get("theme_color") ?? "");
  const version = String(form.get("version") ?? "");
  if (name.length < 2 || name.length > 80 || shortName.length < 2 || shortName.length > 24
    || !/^#[0-9a-fA-F]{6}$/.test(color) || !/^\d{1,9}$/.test(version)) {
    redirect("/settings?error=pwa");
  }
  try {
    await adminFetch("/pwa-settings", "PATCH", {
      name, short_name: shortName, theme_color: color, expected_version: Number(version),
    });
  } catch {
    redirect("/settings?error=pwa");
  }
  revalidatePath("/settings");
  revalidatePath("/manifest.webmanifest");
  redirect("/settings?saved=pwa");
}
