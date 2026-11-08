"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";
import { parseCalendarDate } from "@/lib/persian-calendar";

/** Only a positive integer internal CRM identity is accepted. */
function customerId(form: FormData): string {
  const value = String(form.get("customer_id") ?? "");
  if (!/^[1-9][0-9]*$/.test(value)) redirect("/customers");
  return value;
}
function fail(id: string, error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  redirect(`/customers/${id}?error=${error.code === "reauthentication_required" || error.status === 428 ? "reauth" : error.status === 422 ? "validation" : error.status === 403 ? "permission" : "save"}`);
}

/** Append an immutable support note after server-side RBAC. */
export async function addCustomerNote(form: FormData): Promise<void> {
  const id = customerId(form);
  const content = String(form.get("content") ?? "").trim();
  if (!content || content.length > 4000) redirect(`/customers/${id}?error=validation`);
  try {
    await adminFetch(`/customers/${id}/notes`, "POST", { content });
  } catch (error) { fail(id, error); }
  revalidatePath(`/customers/${id}`);
  redirect(`/customers/${id}?saved=1`);
}

/** Update only CRM tags, assignee and support status. */
export async function saveCustomerProfile(form: FormData): Promise<void> {
  const id = customerId(form);
  const tags = String(form.get("tags") ?? "").split(",").map(value => value.trim()).filter(Boolean);
  const owner = String(form.get("owner_staff_id") ?? "");
  const support_status = String(form.get("support_status") ?? "open");
  if (tags.length > 12 || tags.some(tag => tag.length > 32) ||
      !["open", "pending", "resolved"].includes(support_status) ||
      (owner && !/^[1-9][0-9]*$/.test(owner))) redirect(`/customers/${id}?error=validation`);
  try {
    await adminFetch(`/customers/${id}/profile`, "POST", {
      tags, owner_staff_id: owner ? Number(owner) : null, support_status,
    });
  } catch (error) { fail(id, error); }
  revalidatePath(`/customers/${id}`);
  redirect(`/customers/${id}?saved=1`);
}

/** Require a documented reason to create a time-bounded shop restriction. */
export async function restrictCustomer(form: FormData): Promise<void> {
  const id = customerId(form);
  const blocked = String(form.get("blocked")) === "true";
  const reason = String(form.get("reason") ?? "").trim();
  const until = String(form.get("until") ?? "").trim();
  if (blocked && (reason.length < 8 || reason.length > 500)) {
    redirect(`/customers/${id}?error=reason`);
  }
  let expires: string | null = null;
  if (until) {
    // Interpret calendar dates as the end of the day in the same timezone as legacy local timestamps.
    const date = /^\d{4}-\d{2}-\d{2}$/.test(until)
      ? parseCalendarDate(until) && new Date(`${until}T23:59:59.999`)
      : new Date(until);
    if (!date || !Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) {
      redirect(`/customers/${id}?error=validation`);
    }
    expires = date.toISOString();
  }
  try {
    await adminFetch(`/customers/${id}/restriction`, "POST", {
      blocked, reason, until: expires,
    });
  } catch (error) { fail(id, error); }
  revalidatePath(`/customers/${id}`);
  redirect(`/customers/${id}?saved=1`);
}
