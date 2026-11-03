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

/** Update both provider policies in one audited FastAPI transaction. */
export async function saveChannelFeatures(form: FormData) {
  const items = (["telegram", "bale"] as const).map((platform) => ({
    platform,
    cart_enabled: form.has(`${platform}_cart_enabled`),
    store_credit_enabled: form.has(`${platform}_store_credit_enabled`),
    store_credit_label: String(form.get(`${platform}_store_credit_label`) ?? "").trim(),
  }));
  if (items.some((item) => item.store_credit_label.length < 1 ||
      item.store_credit_label.length > 80)) redirect("/settings?error=channels");
  let failed = false;
  try {
    await adminFetch("/channel-features", "POST", { items });
  } catch {
    failed = true;
  }
  if (failed) redirect("/settings?error=channels");
  revalidatePath("/settings");
  redirect("/settings?saved=channels");
}
