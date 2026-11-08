"use server";

import { revalidatePath } from "next/cache";
import { adminFetch, ApiError } from "@/lib/bridge";
import type { StoreContextSnapshot } from "@/lib/store-context";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Selection = {
  expected_version: number;
  current_store_id: string;
  active_store_ids: string[];
};

export type StoreActionResult =
  | { ok: true; context: StoreContextSnapshot }
  | { ok: false; message: string };

function safeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "اتصال پنل در دسترس نیست.";
  if (error.status === 401) return "نشست منقضی شده است؛ دوباره وارد شوید.";
  if (error.code === "configuration_changed") return "انتخاب Store در نشست دیگری تغییر کرده؛ صفحه را تازه‌سازی کنید.";
  if (error.code === "store_access_denied") return "دسترسی Store تغییر کرده است؛ انتخاب را تازه کنید.";
  return "تغییر Store ثبت نشد؛ مجوز و وضعیت نشست را بررسی کنید.";
}

/** Submit only a proposed Store set; the server independently checks grants. */
export async function selectStoreContext(
  value: Selection,
): Promise<StoreActionResult> {
  const active = value.active_store_ids;
  if (
    !Number.isSafeInteger(value.expected_version) ||
    value.expected_version < 1 ||
    !UUID.test(value.current_store_id) ||
    !Array.isArray(active) ||
    active.length < 1 || active.length > 32 ||
    active.some((id) => !UUID.test(id)) ||
    new Set(active).size !== active.length ||
    !active.includes(value.current_store_id)
  ) {
    return { ok: false, message: "یک یا چند Store معتبر انتخاب کنید." };
  }
  try {
    const data = await adminFetch<StoreContextSnapshot>(
      "/store-context/select", "POST", value,
    );
    revalidatePath("/", "layout");
    return { ok: true, context: data };
  } catch (error) {
    return { ok: false, message: safeError(error) };
  }
}

/** Save a user-level default; other browser sessions keep their own context. */
export async function saveDefaultStore(
  storeId: string, expectedVersion: number,
): Promise<{ ok: true } | { ok: false; message: string }> {
  if (!UUID.test(storeId) ||
    !Number.isSafeInteger(expectedVersion) || expectedVersion < 0) {
    return { ok: false, message: "Store پیش‌فرض نامعتبر است." };
  }
  try {
    await adminFetch("/store-context/default", "POST", {
      store_id: storeId, expected_version: expectedVersion,
    });
    revalidatePath("/", "layout");
    return { ok: true };
  } catch (error) {
    return { ok: false, message: safeError(error) };
  }
}
