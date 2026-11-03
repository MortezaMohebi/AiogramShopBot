"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Save exactly the administrator-selected product or category Many2many
 * grants. Both row locks and new-rule audit history live in FastAPI.
 */
export async function setBotCatalogRules(form: FormData): Promise<void> {
  const botId = String(form.get("bot_id") ?? "");
  if (!UUID.test(botId)) redirect("/bots?error=validation");
  const kind = String(form.get("kind") ?? "");
  const effect = String(form.get("effect") ?? "");
  const version = Number(form.get("expected_version"));
  const target_ids = form.getAll("target_ids").map(value => Number(value));
  if (
    !["product", "category"].includes(kind)
    || !["allow", "deny", "inherit"].includes(effect)
    || !Number.isSafeInteger(version) || version <= 0
    || target_ids.length < 1 || target_ids.length > 100
    || target_ids.some(id => !Number.isSafeInteger(id) || id <= 0)
    || new Set(target_ids).size !== target_ids.length
  ) {
    redirect(`/bots/${botId}?acl_error=validation#catalog-access`);
  }
  let failure: string | null = null;
  try {
    await adminFetch(`/bot-catalog/bots/${botId}/rules`, "POST", {
      kind, effect, expected_version: version, target_ids,
    });
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error.status === 428 ? "reauth"
      : error.status === 409 ? "version"
      : error.status === 403 ? "permission" : "save";
  }
  if (failure) {
    redirect(`/bots/${botId}?acl_error=${failure}#catalog-access`);
  }
  revalidatePath("/bots");
  revalidatePath(`/bots/${botId}`);
  redirect(`/bots/${botId}?acl_kind=${kind}&acl_saved=1#catalog-access`);
}
