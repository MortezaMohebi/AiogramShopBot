"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

/** Persist a reviewed retention policy without touching financial records. */
export async function saveRetentionPolicy(form: FormData): Promise<void> {
  const note = Number(form.get("note_retention_days"));
  const audit = Number(form.get("audit_retention_days"));
  if (!Number.isSafeInteger(note) || !Number.isSafeInteger(audit) ||
      note < 30 || note > 3650 || audit < 365 || audit > 3650) {
    redirect("/customers/retention?error=validation");
  }
  try {
    await adminFetch("/customer-retention", "POST", {
      note_retention_days: note, audit_retention_days: audit,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    redirect(`/customers/retention?error=${error.code === "reauthentication_required" || error.status === 428 ? "reauth" : "save"}`);
  }
  revalidatePath("/customers/retention");
  redirect("/customers/retention?saved=1");
}

/** Purge only old internal notes after an explicit confirmation checkbox. */
export async function purgeCustomerNotes(form: FormData): Promise<void> {
  const run = form.has("confirm");
  let result: {
    ok?: boolean; dry_run?: boolean;
    notes_eligible?: number; notes_deleted?: number;
  } | null;
  try {
    result = await adminFetch("/customer-retention/purge", "POST", {
      dry_run: !run,
      confirmation: run ? "PURGE_EXPIRED_NOTES" : "",
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    redirect(`/customers/retention?error=${error.code === "reauthentication_required" || error.status === 428 ? "reauth" : "purge"}`);
  }
  // Show the backend's confirmed count for the requested mode, never a guessed
  // deletion count or a dry-run response as proof that deletion completed.
  const count = run ? result?.notes_deleted : result?.notes_eligible;
  if (result?.ok !== true || result.dry_run !== !run ||
      typeof count !== "number" || !Number.isSafeInteger(count) || count < 0) {
    redirect("/customers/retention?error=receipt");
  }
  revalidatePath("/customers/retention");
  redirect(`/customers/retention?saved=${run ? "purged" : "preview"}&count=${count}`);
}
