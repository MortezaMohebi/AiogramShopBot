"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

function safeTicketId(value: FormDataEntryValue | null): number {
  const text = String(value ?? "");
  const id = Number(text);
  if (!/^[1-9][0-9]{0,15}$/.test(text) || !Number.isSafeInteger(id)) {
    redirect("/support-tickets?error=validation");
  }
  return id;
}

/** Append one customer-visible, auditable staff reply; no financial mutation. */
export async function replyToTicket(form: FormData): Promise<void> {
  const id = safeTicketId(form.get("ticket_id"));
  const expected_version = Number(form.get("expected_version"));
  const body = String(form.get("body") ?? "").trim();
  if (!Number.isSafeInteger(expected_version) || expected_version < 1 ||
      body.length < 1 || body.length > 4000) {
    redirect(`/support-tickets/${id}?error=validation`);
  }
  try {
    await adminFetch(`/support-tickets/${id}/reply`, "POST", {
      expected_version, body,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 401) redirect("/login?expired=1");
    redirect(`/support-tickets/${id}?error=save`);
  }
  revalidatePath("/support-tickets");
  revalidatePath(`/support-tickets/${id}`);
  redirect(`/support-tickets/${id}?saved=reply`);
}
