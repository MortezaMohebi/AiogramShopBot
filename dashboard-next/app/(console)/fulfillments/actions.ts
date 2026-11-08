"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

/** A manual shipment step cannot mark an unpaid Order as paid. */
export async function advanceFulfillment(form: FormData): Promise<void> {
  const idText = String(form.get("order_id") ?? "");
  const orderId = Number(idText);
  const expected_version = Number(form.get("expected_version"));
  const next_status = String(form.get("next_status") ?? "");
  const carrier = String(form.get("carrier") ?? "").trim();
  const tracking_code = String(form.get("tracking_code") ?? "").trim();
  if (!/^[1-9][0-9]{0,15}$/.test(idText) ||
    !Number.isSafeInteger(orderId) ||
    !Number.isSafeInteger(expected_version) || expected_version < 1 ||
    !["ready", "shipped", "delivered"].includes(next_status) ||
    carrier.length > 80 || tracking_code.length > 120 ||
    (next_status === "shipped" && (!carrier || !tracking_code))) {
    redirect("/fulfillments?error=validation");
  }
  try {
    await adminFetch(`/fulfillments/${orderId}/advance`, "POST", {
      expected_version, next_status,
      carrier: carrier || null, tracking_code: tracking_code || null,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 401) redirect("/login?expired=1");
    redirect("/fulfillments?error=save");
  }
  revalidatePath("/fulfillments");
  redirect("/fulfillments?saved=1");
}
