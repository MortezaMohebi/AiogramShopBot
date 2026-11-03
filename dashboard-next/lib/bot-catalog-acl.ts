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
  kind: CatalogRuleKind;
  default_effect: "allow" | "deny";
  policy_ready: boolean;
  items: BotCatalogCandidate[];
  total: number;
  page: number;
  page_size: number;
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
