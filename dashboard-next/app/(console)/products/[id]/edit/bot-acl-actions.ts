"use server";

import { bridgeFetch } from "@/lib/bridge";
import { parseProductBotAssignments, type ProductBotAssignment } from "@/lib/bot-catalog-acl";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { sectionRpcError } from "@/lib/section-rpc-server";
import { readSession } from "@/lib/session";

export async function setProductBotAccess(
  productId: number, input: ProductBotAssignment[],
): Promise<SectionRpcResult<{ changed: number }>> {
  const assignments = parseProductBotAssignments(input);
  if (!Number.isSafeInteger(productId) || productId <= 0 || !assignments) return { ok: false, code: "validation" };
  const session = await readSession();
  if (!session) return { ok: false, code: "session_expired" };
  try {
    const data = await bridgeFetch<{ ok: boolean; changed: number }>(
      `/bot-catalog/products/${productId}/rules`, "POST", { assignments }, session,
    );
    if (data?.ok !== true || !Number.isInteger(data.changed) || data.changed < 0 || data.changed > assignments.length) {
      return { ok: false, code: "outcome_unknown" };
    }
    return { ok: true, data };
  } catch (error) {
    return { ok: false, code: sectionRpcError(error, true) };
  }
}
