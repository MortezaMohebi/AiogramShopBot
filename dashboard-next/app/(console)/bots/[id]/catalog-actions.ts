"use server";

import { catalogBotId, parseCatalogChange, type CatalogChange, type CatalogChangeReceipt } from "@/lib/bot-catalog-acl";
import { bridgeFetch } from "@/lib/bridge";
import { sectionRpcError } from "@/lib/section-rpc-server";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { readSession } from "@/lib/session";

export async function setBotCatalogRules(
  botId: string, input: CatalogChange,
): Promise<SectionRpcResult<CatalogChangeReceipt>> {
  const change = parseCatalogChange(input);
  if (typeof botId !== "string" || !catalogBotId.test(botId) || !change) {
    return { ok: false, code: "validation" };
  }
  const session = await readSession();
  if (!session) return { ok: false, code: "session_expired" };
  try {
    const receipt = await bridgeFetch<CatalogChangeReceipt>(
      `/bot-catalog/bots/${botId}/rules`, "POST", change, session,
    );
    if (
      receipt?.ok !== true || !Number.isInteger(receipt.changed) ||
      receipt.changed < 0 || receipt.changed > change.target_ids.length ||
      receipt.version !== change.expected_version + Number(receipt.changed > 0)
    ) return { ok: false, code: "outcome_unknown" };
    return { ok: true, data: receipt };
  } catch (error) {
    return { ok: false, code: sectionRpcError(error, true) };
  }
}
