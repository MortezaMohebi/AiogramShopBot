import { catalogListParams, type BotCatalogRuleList, type CatalogAuditRow, type CatalogListQuery } from "@/lib/bot-catalog-acl";
import { readSectionRpc } from "@/lib/section-rpc";

export function listBotCatalog(botId: string, query: CatalogListQuery, signal: AbortSignal) {
  return readSectionRpc<BotCatalogRuleList>(
    `/api/admin/bot-catalog/${encodeURIComponent(botId)}?${catalogListParams(query)}`, signal,
  );
}

export function listBotCatalogAudit(botId: string, signal?: AbortSignal) {
  return readSectionRpc<{ items: CatalogAuditRow[] }>(
    `/api/admin/bot-catalog/${encodeURIComponent(botId)}?audit=1`, signal,
  );
}
