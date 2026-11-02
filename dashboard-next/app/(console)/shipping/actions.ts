"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Shipping fees are integral rials and always validated by Python. */
export async function saveShipping(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  const payload = {
    name: String(form.get("name") ?? "").trim(),
    price_irr: String(form.get("price_irr") ?? "0"),
    position: Number(form.get("position") ?? 0),
    is_active: form.has("is_active"),
  };
  let failed = false;
  try {
    await adminFetch(
      id ? `/shipping/${id}` : "/shipping",
      id ? "PATCH" : "POST",
      payload,
    );
  } catch {
    failed = true;
  }
  if (failed) redirect("/shipping?error=1");
  revalidatePath("/shipping");
  redirect("/shipping?saved=1");
}
