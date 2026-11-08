"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CODE = /^[a-z][a-z0-9_-]{0,31}$/;

function fail(error: unknown): never {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.code === "reauthentication_required" || error.status === 428) redirect("/uoms?error=reauth");
  const allowed = new Set([
    "invalid_uom", "uom_already_exists", "uom_category_not_found",
    "store_switch_required", "store_permission_denied",
    "configuration_changed",
  ]);
  redirect(`/uoms?error=${error.code && allowed.has(error.code)
    ? error.code : "save"}`);
}

function required(form: FormData, key: string, max: number): string {
  const value = String(form.get(key) ?? "").trim();
  if (!value || value.length > max) redirect("/uoms?error=validation");
  return value;
}

/** Create the conversion category and reference unit in one Store transaction. */
export async function createUomCategory(form: FormData): Promise<void> {
  const storeId = required(form, "store_id", 36);
  const code = required(form, "code", 32);
  const base_code = required(form, "base_code", 32);
  if (!UUID.test(storeId) || !CODE.test(code) || !CODE.test(base_code)) {
    redirect("/uoms?error=validation");
  }
  try {
    await adminFetch(`/stores/${storeId}/uom-categories`, "POST", {
      code,
      name: required(form, "name", 120),
      base_code,
      base_name: required(form, "base_name", 120),
      base_symbol: required(form, "base_symbol", 24),
    });
  } catch (error) { fail(error); }
  revalidatePath("/uoms");
  redirect("/uoms?saved=category");
}

/** Add a new rational conversion unit to one existing Store category. */
export async function createUomUnit(form: FormData): Promise<void> {
  const storeId = required(form, "store_id", 36);
  const category_id = required(form, "category_id", 36);
  const code = required(form, "code", 32);
  const ratio_num = Number(form.get("ratio_num"));
  const ratio_den = Number(form.get("ratio_den"));
  const rounding = String(form.get("rounding") ?? "");
  if (!UUID.test(storeId) || !UUID.test(category_id) || !CODE.test(code) ||
    !Number.isSafeInteger(ratio_num) || ratio_num < 1 || ratio_num > 1_000_000_000 ||
    !Number.isSafeInteger(ratio_den) || ratio_den < 1 || ratio_den > 1_000_000_000 ||
    !/^\d{1,7}(\.\d{1,6})?$/.test(rounding) || Number(rounding) <= 0) {
    redirect("/uoms?error=validation");
  }
  try {
    await adminFetch(`/stores/${storeId}/uoms`, "POST", {
      category_id, code,
      name: required(form, "name", 120),
      symbol: required(form, "symbol", 24),
      ratio_num, ratio_den, rounding,
    });
  } catch (error) { fail(error); }
  revalidatePath("/uoms");
  redirect("/uoms?saved=unit");
}
