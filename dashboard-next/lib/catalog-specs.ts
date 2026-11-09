import { requestBrowserChallenge } from "@/lib/browser-challenge";

export type CatalogKind = "attributes" | "values";
export type CatalogSpec = {
  id: number;
  label: string;
  used?: boolean;
  unit?: string | null;
  aliases?: string[];
  definition_id?: number;
  attribute_label?: string;
};
type SpecPayload = { label: string; unit?: string | null; aliases?: string[]; definition_id?: number };
export type CatalogPage = { items: CatalogSpec[]; has_more: boolean };

async function request<T>(params: URLSearchParams, method: string, signal?: AbortSignal, payload?: SpecPayload): Promise<T> {
  const challenge = method === "GET" ? undefined : await requestBrowserChallenge();
  const response = await fetch(`/api/admin/catalog-specs?${params}`, {
    method, credentials: "same-origin", cache: "no-store",
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000),
    headers: {
      Accept: "application/json",
      ...(challenge ? { "x-shop-login-challenge": challenge } : {}),
      ...(payload ? { "content-type": "application/json" } : {}),
    },
    body: payload ? JSON.stringify(payload) : undefined,
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result?.code ?? "service_unavailable");
  return result as T;
}

export function readCatalogSpecs(store: string, kind: CatalogKind, q: string, page: number,
  definitionId?: number, signal?: AbortSignal): Promise<CatalogPage> {
  const params = new URLSearchParams({ store, kind, q, page: String(page) });
  if (definitionId) params.set("definition_id", String(definitionId));
  return request(params, "GET", signal);
}

export function saveCatalogSpec(store: string, kind: CatalogKind, payload: SpecPayload, id?: number): Promise<CatalogSpec> {
  const params = new URLSearchParams({ store, kind });
  if (id) params.set("id", String(id));
  return request(params, id ? "PATCH" : "POST", undefined, payload);
}

export function deleteCatalogSpec(store: string, kind: CatalogKind, id: number): Promise<{ deleted: boolean }> {
  return request(new URLSearchParams({ store, kind, id: String(id) }), "DELETE");
}

export function catalogSpecError(error: unknown) {
  const messages: Record<string, string> = {
    catalog_spec_in_use: "این مورد در محصول استفاده می‌شود. ابتدا آن را از محصولات مربوط بردارید.",
    catalog_spec_conflict: "موردی با همین مشخصات از قبل وجود دارد. آن را جست‌وجو و انتخاب کنید.",
    catalog_term_parent_fixed: "ویژگی این مقدار قابل تغییر نیست.",
    invalid_catalog_spec: "عنوان و فیلدهای این مورد را بررسی کنید.",
    not_found: "این مورد دیگر در فروشگاه موجود نیست. فهرست را دوباره بررسی کنید.",
    session_expired: "نشست شما منقضی شده است. دوباره وارد شوید.",
    permission_denied: "برای این کار دسترسی ندارید.",
    security_check_failed: "بررسی امنیتی انجام نشد. دوباره تلاش کنید.",
  };
  return messages[error instanceof Error ? error.message : ""] ?? "نتیجه تأیید نشد. اتصال و فهرست را بررسی کنید.";
}
