/** Typed, non-secret Many2many bot catalog policy contracts. */

export type CatalogEffect = "allow" | "deny" | "inherit";
export type CatalogRuleKind = "product" | "category";

export interface BotCatalogCandidate {
  id: number;
  name: string;
  is_published: boolean;
  category_id: number | null;
  effect: CatalogEffect;
  effective_access: boolean | null;
}

export interface BotCatalogRuleList {
  bot_id: string;
  version: number;
  kind: CatalogRuleKind;
  default_effect: "allow" | "deny";
  policy_ready: boolean;
  items: BotCatalogCandidate[];
  total: number;
  page: number;
  page_size: number;
}

export interface CatalogAuditRow {
  object_type: CatalogRuleKind;
  object_id: number;
  old_effect: CatalogEffect;
  new_effect: CatalogEffect;
  actor_id: number;
  created_at: string | null;
}

export interface CatalogListQuery {
  kind: CatalogRuleKind;
  q: string;
  effect: CatalogEffect | null;
  page: number;
}

export interface CatalogChange {
  kind: CatalogRuleKind;
  effect: CatalogEffect;
  expected_version: number;
  target_ids: number[];
}

export interface CatalogChangeReceipt {
  ok: true;
  changed: number;
  version: number;
}

export const catalogBotId = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const isKind = (value: unknown): value is CatalogRuleKind =>
  value === "product" || value === "category";
const isEffect = (value: unknown): value is CatalogEffect =>
  value === "allow" || value === "deny" || value === "inherit";
const positiveInt = (value: unknown): value is number =>
  typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const pageNumber = (value: string) =>
  /^[1-9][0-9]{0,5}$/.test(value) && Number(value) <= 100_000 ? Number(value) : null;

/** Browser URL state is namespaced so other sections can share the page. */
export const botCatalogQuery = {
  keys: ["acl_kind", "acl_q", "acl_effect", "acl_page"],
  read(params: Pick<URLSearchParams, "get">): CatalogListQuery {
    const effect = params.get("acl_effect");
    return {
      kind: params.get("acl_kind") === "category" ? "category" : "product",
      q: (params.get("acl_q") ?? "").trim().slice(0, 100),
      effect: isEffect(effect) ? effect : null,
      page: pageNumber(params.get("acl_page") ?? "") ?? 1,
    };
  },
  write({ kind, q, effect, page }: CatalogListQuery): URLSearchParams {
    const params = new URLSearchParams();
    if (kind === "category") params.set("acl_kind", kind);
    if (q) params.set("acl_q", q);
    if (effect) params.set("acl_effect", effect);
    if (page > 1) params.set("acl_page", String(page));
    return params;
  },
};

export function catalogListParams({ kind, q, effect, page }: CatalogListQuery): URLSearchParams {
  const params = new URLSearchParams({ kind, q, page: String(page) });
  if (effect) params.set("effect", effect);
  return params;
}

export function parseCatalogListParams(params: URLSearchParams): CatalogListQuery | null {
  for (const key of params.keys()) {
    if (!["kind", "q", "effect", "page"].includes(key) || params.getAll(key).length !== 1) return null;
  }
  const kind = params.get("kind") ?? "product";
  const q = params.get("q") ?? "";
  const effect = params.get("effect");
  const page = pageNumber(params.get("page") ?? "1");
  if (!isKind(kind) || q.length > 100 || (effect !== null && !isEffect(effect)) || page === null) return null;
  return { kind, q: q.trim(), effect, page };
}

export function parseCatalogChange(value: unknown): CatalogChange | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const { kind, effect, expected_version, target_ids } = value as Partial<CatalogChange>;
  if (
    Object.keys(value).length !== 4 || !isKind(kind) || !isEffect(effect) ||
    !positiveInt(expected_version) || !Array.isArray(target_ids) ||
    target_ids.length < 1 || target_ids.length > 100 ||
    !Array.from(target_ids).every(positiveInt) || new Set(target_ids).size !== target_ids.length
  ) return null;
  return { kind, effect, expected_version, target_ids };
}

export interface ProductBotCatalogCandidate {
  id: string;
  name: string;
  platform: "telegram" | "bale";
  status: string;
  version: number;
  effect: CatalogEffect;
  default_effect: "allow" | "deny";
}

export interface ProductBotCatalogList {
  product_id: number;
  bots: ProductBotCatalogCandidate[];
  total: number;
  page: number;
  page_size: number;
}

export const catalogEffectLabels: Record<CatalogEffect, string> = {
  allow: "مجاز",
  deny: "ممنوع",
  inherit: "ارث‌بری",
};

export function catalogBotLabel(platform: string): string {
  return platform === "telegram" ? "تلگرام" : "بله";
}
