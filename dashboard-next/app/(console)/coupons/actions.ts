"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Coupon issuance changes the authoritative SQLAlchemy marketing policy. */
export async function saveCoupon(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  const rawExpiry = String(form.get("expires_at") ?? "");
  const payload = {
    code: String(form.get("code") ?? "").trim().toUpperCase(),
    discount_type: String(form.get("discount_type") ?? "fixed"),
    value: String(form.get("value") ?? "0"),
    minimum_subtotal_irr: String(form.get("minimum_subtotal_irr") ?? "0"),
    max_uses: form.get("max_uses") ? Number(form.get("max_uses")) : null,
    expires_at: rawExpiry ? `${rawExpiry}T23:59:59+00:00` : null,
    is_active: form.has("is_active"),
  };
  let failed = false;
  try {
    await adminFetch(
      id ? `/coupons/${id}` : "/coupons",
      id ? "PATCH" : "POST",
      payload,
    );
  } catch {
    failed = true;
  }
  if (failed) redirect("/coupons?error=1");
  revalidatePath("/coupons");
  redirect("/coupons?saved=1");
}
