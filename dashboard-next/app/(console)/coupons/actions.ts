"use server";

import { redirect } from "next/navigation";
import { saveDraftMutation } from "@/lib/draft-mutation";

function couponsFields(form: FormData) {
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
  return payload;
}

/** Coupon issuance changes the authoritative SQLAlchemy marketing policy. */
export async function saveCoupon(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  if (id && !/^[1-9]\d*$/.test(id)) redirect("/coupons?error=1");
  const result = await saveDraftMutation(id ? `/coupons/${id}` : "/coupons", id ? "PATCH" : "POST",
    couponsFields(form), "/coupons");
  if (!result.ok) redirect("/coupons?error=1");
  redirect("/coupons?saved=1");
}

export async function saveCouponDraft(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  if (!/^[1-9]\d*$/.test(id)) return { ok: false, code: "validation" } as const;
  return saveDraftMutation(`/coupons/${id}`, "PATCH", couponsFields(form), "/coupons");
}
