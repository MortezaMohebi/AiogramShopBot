"use server";

import { revalidatePath } from "next/cache";
import { ApiError, adminFetch } from "@/lib/bridge";
import { normalizeStoreName } from "@/lib/store-name";

const DRAFT_SLUG = /^store-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type StoreResult = { ok: true } | { ok: false; message: string; reauthenticate?: boolean };
type SalesState = "active" | "paused";

/** Create a paused Store using the live session and a stable draft ID. */
export async function createStore(name: string, slug: string): Promise<StoreResult> {
  const normalized = normalizeStoreName(name);
  if (!normalized || typeof slug !== "string" || !DRAFT_SLUG.test(slug)) {
    return { ok: false, message: "نام شرکت یا فروشگاه معتبر نیست. نام را بررسی کنید." };
  }
  try {
    const receipt = await adminFetch<{ ok: boolean }>("/stores", "POST", {
      name: normalized, slug,
    });
    if (receipt.ok !== true) {
      return { ok: false, message: "نتیجهٔ ثبت مشخص نیست. ابتدا فهرست فروشگاه‌ها را بررسی کنید." };
    }
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.code === "reauthentication_required") {
      return { ok: false, message: "برای ساخت فروشگاه، ابتدا هویت خود را در حساب من تأیید کنید.", reauthenticate: true };
    }
    if (error.code === "invalid_registry_name") {
      return { ok: false, message: "نام شرکت یا فروشگاه معتبر نیست. نام را بررسی کنید." };
    }
    if (error.code === "store_slug_exists") {
      return { ok: false, message: "این درخواست قبلاً ثبت شده است. فهرست فروشگاه‌ها را تازه‌سازی کنید." };
    }
    if (error.status === 403) {
      return { ok: false, message: "این حساب مجوز ساخت فروشگاه را ندارد." };
    }
    return { ok: false, message: "نتیجهٔ ثبت مشخص نیست. ابتدا فهرست فروشگاه‌ها را بررسی کنید." };
  }
  revalidatePath("/", "layout");
  return { ok: true };
}

/** Switch sales eligibility for the current Store after explicit confirmation. */
export async function changeStoreState(
  storeId: string, expected: SalesState, state: SalesState,
): Promise<StoreResult> {
  if (typeof storeId !== "string" || !UUID.test(storeId) ||
      !((expected === "active" && state === "paused") ||
        (expected === "paused" && state === "active"))) {
    return { ok: false, message: "درخواست تغییر وضعیت معتبر نیست." };
  }
  try {
    const receipt = await adminFetch<{ ok: boolean }>(`/stores/${storeId}/state`, "POST", {
      expected_state: expected, state,
    });
    if (receipt.ok !== true) {
      return { ok: false, message: "نتیجهٔ تغییر وضعیت مشخص نیست. صفحه را تازه‌سازی کنید." };
    }
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.code === "reauthentication_required") {
      return { ok: false, message: "ابتدا هویت خود را در حساب من تأیید کنید.", reauthenticate: true };
    }
    if (error.code === "store_has_live_activity") {
      return { ok: false, message: "این فروشگاه ربات در حال اجرا، اتصال در حال تغییر یا پرداخت تعیین‌تکلیف‌نشده دارد. پیش از تغییر وضعیت، آن‌ها را بررسی کنید." };
    }
    if (error.code === "configuration_changed") {
      return { ok: false, message: "وضعیت فروشگاه تغییر کرده است. صفحه را تازه‌سازی کنید." };
    }
    if (error.status === 403 || error.status === 409) {
      return { ok: false, message: "فروشگاه جاری و دسترسی مدیریتی خود را بررسی کنید." };
    }
    return { ok: false, message: "نتیجهٔ تغییر وضعیت مشخص نیست. صفحه را تازه‌سازی کنید." };
  }
  revalidatePath("/", "layout");
  return { ok: true };
}
