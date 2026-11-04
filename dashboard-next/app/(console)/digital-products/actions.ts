"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";

function productId(form: FormData): number {
  const raw = String(form.get("product_id") ?? "");
  const value = Number(raw);
  if (!/^[1-9][0-9]{0,14}$/.test(raw) || !Number.isSafeInteger(value)) {
    redirect("/products?error=validation");
  }
  return value;
}

function credentialProof(form: FormData) {
  const current_password = String(form.get("current_password") ?? "");
  const second_factor = String(form.get("second_factor") ?? "").trim();
  if (!current_password || current_password.length > 256 ||
    !/^[0-9]{6}$/.test(second_factor)) {
    redirect("/account?error=reauth");
  }
  return { current_password, second_factor };
}

function safeFailure(error: unknown, id: number): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  const allowed = new Set([
    "digital_asset_not_ready", "digital_asset_change_blocked",
    "digital_license_import_denied", "configuration_changed",
    "store_access_denied", "store_switch_required",
    "store_permission_denied", "reauthentication_required",
  ]);
  const code = error.code && allowed.has(error.code) ?
    error.code : "save";
  redirect(`/products/${id}/edit?digital_error=${code}`);
}

/** Switch mode only after fresh MFA, without exposing old private license keys. */
export async function activateLicenseMode(form: FormData): Promise<void> {
  const id = productId(form);
  try {
    await adminFetch(
      `/digital-products/${id}/license-mode`, "POST", {
        confirmation: "ACTIVATE_LICENSE_MODE",
        ...credentialProof(form),
      },
    );
  } catch (error) {
    safeFailure(error, id);
  }
  revalidatePath(`/products/${id}/edit`);
  redirect(`/products/${id}/edit?digital_saved=mode`);
}

/** Import bounded license codes as a signed, nonlogged and one-time request. */
export async function importLicenseCodes(form: FormData): Promise<void> {
  const id = productId(form);
  const raw = String(form.get("license_codes") ?? "");
  const codes = raw.split(/\r?\n/).map((code) => code.trim()).filter(Boolean);
  if (
    raw.length > 75_000 || codes.length === 0 || codes.length > 500 ||
    new Set(codes).size !== codes.length ||
    codes.some((code) => code.length < 4 || code.length > 128 ||
      [...code].some((char) => {
        const codepoint = char.charCodeAt(0);
        return codepoint < 32 || codepoint === 127;
      }))
  ) {
    redirect(`/products/${id}/edit?digital_error=validation`);
  }
  try {
    await adminFetch(
      `/digital-products/${id}/licenses`, "POST", {
        codes, ...credentialProof(form),
      },
      30_000,
    );
  } catch (error) {
    safeFailure(error, id);
  }
  revalidatePath(`/products/${id}/edit`);
  redirect(`/products/${id}/edit?digital_saved=licenses`);
}
