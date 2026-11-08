"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const POSITIVE_ID = /^[1-9][0-9]{0,15}$/;

/** Seal the supplied codes in Python; never store or return plaintext in UI. */
export async function saveDigitalLicenses(form: FormData): Promise<void> {
  const id = String(form.get("product_id") ?? "");
  if (!POSITIVE_ID.test(id)) redirect("/products?error=validation");

  const raw = String(form.get("license_codes") ?? "");
  const codes = raw.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!codes.length || codes.length > 100 ||
      codes.some(line => line.length < 4 || line.length > 128 || /[\x00-\x1f\x7f]/.test(line)) ||
      !current_password || current_password.length > 256 ||
      !/^[0-9]{6}$/.test(second_factor)) {
    redirect(`/products/${id}/digital?error=validation`);
  }
  try {
    await adminFetch(`/products/${id}/digital-licenses`, "POST", {
      codes, current_password, second_factor,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 401) redirect("/login?expired=1");
    redirect(`/products/${id}/digital?error=${
      error.code === "reauthentication_required" || error.status === 428 ? "reauth" : "save"
    }`);
  }
  revalidatePath(`/products/${id}/digital`);
  revalidatePath(`/products/${id}/edit`);
  redirect(`/products/${id}/digital?saved=licenses`);
}
