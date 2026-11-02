"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Update only merchant-facing copy; never expose secrets to a web form. */
export async function saveSettings(form: FormData) {
  const keys = ["brand_name", "welcome_message", "faq_text", "support_url"] as const;
  const payload = Object.fromEntries(
    keys.map((key) => [key, String(form.get(key) ?? "").trim()]),
  );
  let failed = false;
  try {
    await adminFetch("/settings", "PATCH", payload);
  } catch {
    failed = true;
  }
  if (failed) redirect("/settings?error=1");
  revalidatePath("/settings");
  revalidatePath("/dashboard");
  redirect("/settings?saved=1");
}


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
