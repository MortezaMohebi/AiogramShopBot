"use server";

import { adminFetch, ApiError } from "@/lib/bridge";
import type {
  ModelFilter, ModelGroupResult, ModelName, ModelSearchRequest,
  ModelSearchResult, TimeGranularity,
} from "@/lib/model-data";

const VALID = new Set(["products", "customers", "orders"]);

export type DataResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string };

/** Return safe failures without ever reflecting a private backend body. */
function safeFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return "نشست پایان یافته است؛ دوباره وارد شوید.";
    if (error.status === 403) return "مجوز مشاهدهٔ این داده‌ها را ندارید.";
    if (error.code === "store_access_denied") return "Store مجاز نیست.";
    if (error.code === "unknown_model_field") return "فیلد انتخاب‌شده مجاز نیست.";
    if (error.code === "invalid_model_filter") return "عبارت جستجو معتبر نیست.";
  }
  return "جستجو انجام نشد؛ اتصال و مجوزهای مدل را بررسی کنید.";
}

/** Use the same backend registry as exports, never client-built SQL text. */
export async function searchDataModel(
  model: ModelName,
  request: ModelSearchRequest,
): Promise<DataResult<ModelSearchResult>> {
  if (!VALID.has(model)) return { ok: false, error: "مدل نامعتبر است." };
  if (!Array.isArray(request.filters) || request.filters.length > 10) {
    return { ok: false, error: "تعداد فیلترها مجاز نیست." };
  }
  try {
    const data = await adminFetch<ModelSearchResult>(
      `/data-models/${model}/search`, "POST", request,
    );
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: safeFailure(error) };
  }
}

/** Group only registered fields and UTC time buckets. */
export async function groupDataModel(
  model: ModelName,
  field: string,
  granularity: TimeGranularity | null,
  filters: ModelFilter[],
): Promise<DataResult<ModelGroupResult>> {
  if (!VALID.has(model) || !Array.isArray(filters) || filters.length > 10) {
    return { ok: false, error: "درخواست Group By نامعتبر است." };
  }
  try {
    const data = await adminFetch<ModelGroupResult>(
      `/data-models/${model}/group`, "POST", {
        field, granularity, filters,
      },
    );
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: safeFailure(error) };
  }
}
