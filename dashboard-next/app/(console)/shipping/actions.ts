"use server";

import { redirect } from "next/navigation";
import { saveDraftMutation } from "@/lib/draft-mutation";

function shippingFields(form: FormData) {
  const payload = {
    name: String(form.get("name") ?? "").trim(),
    price_irr: String(form.get("price_irr") ?? "0"),
    position: Number(form.get("position") ?? 0),
    is_active: form.has("is_active"),
  };
  return payload;
}

/** Shipping fees are integral rials and always validated by Python. */
export async function saveShipping(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  if (id && !/^[1-9]\d*$/.test(id)) redirect("/shipping?error=1");
  const result = await saveDraftMutation(id ? `/shipping/${id}` : "/shipping", id ? "PATCH" : "POST",
    shippingFields(form), "/shipping");
  if (!result.ok) redirect("/shipping?error=1");
  redirect("/shipping?saved=1");
}

export async function saveShippingDraft(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  if (!/^[1-9]\d*$/.test(id)) return { ok: false, code: "validation" } as const;
  return saveDraftMutation(`/shipping/${id}`, "PATCH", shippingFields(form), "/shipping");
}
