"use server";

import { bridgeFetch } from "@/lib/bridge";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { sectionRpcError } from "@/lib/section-rpc-server";
import { readSession } from "@/lib/session";

export async function saveDisplayOrder(
  kind: "categories" | "product-media" | "campaign-media",
  parentId: number | null,
  expected: number[],
  ids: number[],
): Promise<SectionRpcResult<{ ids: number[] }>> {
  const valid = (list: unknown): list is number[] => Array.isArray(list) && list.length >= 2
    && list.length <= 2000 && list.every((id) => Number.isSafeInteger(id) && id > 0);
  if (!valid(expected) || !valid(ids)) return { ok: false, code: "validation" };
  let path: string;
  if (kind === "categories" && (parentId === null || Number.isSafeInteger(parentId) && parentId > 0)) {
    path = parentId === null ? "/categories/order" : `/categories/order?parent_id=${parentId}`;
  }
  else if (parentId !== null && Number.isSafeInteger(parentId) && parentId > 0
    && (kind === "product-media" || kind === "campaign-media")) {
    path = `/${kind === "product-media" ? "products" : "campaigns"}/${parentId}/media/order`;
  } else return { ok: false, code: "validation" };
  const session = await readSession();
  if (!session) return { ok: false, code: "session_expired" };
  try {
    const data = await bridgeFetch<{ ids: number[] }>(path, "POST", { expected, ids }, session);
    if (!Array.isArray(data?.ids) || data.ids.length !== ids.length || data.ids.some((id, index) => id !== ids[index])) {
      return { ok: false, code: "outcome_unknown" };
    }
    return { ok: true, data };
  } catch (error) {
    return { ok: false, code: sectionRpcError(error, true) };
  }
}
