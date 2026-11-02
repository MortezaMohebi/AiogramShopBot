"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Make only the guarded, auditable prepayment accept/reject decision. */
export async function reviewOrder(form: FormData) {
  const id = String(form.get("order_id") ?? "").trim();
  const decision = String(form.get("decision") ?? "").trim();
  const expected = decision === "accept" ? "ACCEPT_UNPAID_ORDER" : "REJECT_UNPAID_ORDER";
  if (
    !/^[1-9]\d*$/.test(id) ||
    !["accept", "reject"].includes(decision) ||
    String(form.get("confirmation") ?? "").trim() !== expected
  ) {
    redirect("/orders?error=confirmation");
  }

  let failed = false;
  try {
    await adminFetch(`/orders/${id}/review`, "POST", { decision, confirmation: expected });
  } catch {
    failed = true;
  }
  if (failed) redirect("/orders?error=review");
  revalidatePath("/orders");
  revalidatePath("/dashboard");
  redirect("/orders?saved=1");
}
