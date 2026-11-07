"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";
import { isServiceKey } from "@/lib/service-controls";

/** Only names and revisions shown by the control plane are accepted. */
export async function changeService(form: FormData): Promise<void> {
  const key = String(form.get("key") ?? "");
  const choice = String(form.get("choice") ?? "");
  const revision = String(form.get("version") ?? "");
  if (!isServiceKey(key) || !["enable", "disable", "default"].includes(choice)
    || !/^\d{1,9}$/.test(revision)) {
    redirect("/services?error=validation");
  }
  try {
    await adminFetch(`/services/${key}`, "POST", {
      enabled: choice === "default" ? null : choice === "enable",
      expected_version: Number(revision),
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    const code = error.code === "reauthentication_required" ? "reauth"
      : error.code === "service_control_conflict" ? "conflict"
        : error.code === "service_prerequisite_missing" ? "prerequisite" : "save";
    redirect(`/services?error=${code}`);
  }
  revalidatePath("/services");
  redirect("/services?saved=1");
}
