"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

function text(form: FormData, field: string): string {
  return String(form.get(field) ?? "").trim();
}

/** Adjust only merchant store-credit using a durable per-form idempotency key. */
export async function adjustWallet(form: FormData) {
  const direction = text(form, "direction");
  const identityId = text(form, "identity_id");
  const amount = text(form, "amount_irr");
  const key = text(form, "operation_id");
  if (
    !["credit", "debit"].includes(direction) ||
    !/^[1-9]\d*$/.test(identityId) ||
    !/^[1-9]\d*$/.test(amount) ||
    !/^[0-9a-f-]{36}$/i.test(key) ||
    text(form, "confirmation") !== "CREDIT_CONFIRMED"
  ) {
    redirect("/finance?error=validation");
  }
  let failed = false;
  try {
    await adminFetch("/wallets/adjust", "POST", {
      direction,
      // Pydantic validates decimal identifiers exactly; avoid JS number rounding.
      identity_id: identityId,
      amount_irr: Number(amount),
      operation_id: key,
      reason: text(form, "reason"),
      confirmation: "CREDIT_CONFIRMED",
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/finance?error=wallet");
  revalidatePath("/finance");
  revalidatePath("/reports");
  redirect("/finance?saved=wallet");
}

/** Existing Python services alone can confirm or execute provider refunds. */
export async function resolveRefund(form: FormData) {
  const id = text(form, "case_id");
  const action = text(form, "action");
  const confirmation = text(form, "confirmation");
  if (
    !/^[1-9]\d*$/.test(id) ||
    !["manual", "store_credit", "stars"].includes(action) ||
    confirmation !== (action === "stars" ? "REFUND_STARS_EXECUTE" : "REFUND_VERIFIED")
  ) {
    redirect("/finance?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/refunds/${id}/resolve`, "POST", {
      action,
      provider_reference: text(form, "provider_reference"),
      confirmation,
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/finance?error=refund");
  revalidatePath("/finance");
  revalidatePath("/orders");
  revalidatePath("/reports");
  redirect("/finance?saved=refund");
}
