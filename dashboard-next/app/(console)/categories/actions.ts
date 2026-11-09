"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch, bridgeFetch } from "@/lib/bridge";
import type { SectionRpcResult } from "@/lib/section-rpc";
import { sectionRpcError } from "@/lib/section-rpc-server";
import { readSession } from "@/lib/session";

/** Save a category in the original PostgreSQL model used by both bots. */
export async function saveCategory(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  const is_published = form.has("is_published");
  // Creation allocates the next position in PostgreSQL; only edits accept one.
  const position = form.get("position");
  const parent = String(form.get("parent_id") ?? "");
  const payload = { name, is_published,
    ...(form.has("parent_id") ? { parent_id: parent ? Number(parent) : null } : {}), ...(id && position !== null ? { position: Number(position) } : {}) };
  let error = false;
  try {
    await adminFetch(
      id ? `/categories/${id}` : "/categories",
      id ? "PATCH" : "POST",
      payload,
    );
  } catch {
    error = true;
  }
  if (error) redirect("/categories?error=1");
  revalidatePath("/categories");
  revalidatePath("/products");
  redirect("/categories?saved=1");
}

export async function saveCategoryDraft(id: number, patch: {
  name?: string; parent_id?: number | null; is_published?: boolean;
}): Promise<SectionRpcResult<{ id: number }>> {
  if (!Number.isSafeInteger(id) || id < 1) return { ok: false, code: "validation" };
  const session = await readSession();
  if (!session) return { ok: false, code: "session_expired" };
  try {
    const result = await bridgeFetch<{ id: number }>(`/categories/${id}`, "PATCH", patch, session);
    if (result?.id !== id) return { ok: false, code: "outcome_unknown" };
    revalidatePath("/categories");
    revalidatePath("/products");
    return { ok: true, data: result };
  } catch (error) {
    return { ok: false, code: sectionRpcError(error, true) };
  }
}
