"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Update only merchant-facing copy; never expose secrets to a web form. */
export async function saveSettings(form: FormData) {
  const keys = ["brand_name", "welcome_message", "faq_text", "support_url"] as const;
  const payload = Object.fromEntries(
    keys.map((key) => [key, String(form.get(key) ?? "").trim()]),
  );
  let failed = false;
  try {
    await adminFetch("/settings", "PATCH", payload);
  } catch {
    failed = true;
  }
  if (failed) redirect("/settings?error=1");
  revalidatePath("/settings");
  revalidatePath("/dashboard");
  redirect("/settings?saved=1");
}
