"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * Update only selected bot/product Many2many links in an atomic Backend
 * transaction. Nothing on this form updates another product's price/stock.
 */
export async function setProductBotAccess(form: FormData): Promise<void> {
  const productId = String(form.get("product_id") ?? "");
  if (!/^[1-9][0-9]*$/.test(productId)) redirect("/products");
  const effect = String(form.get("effect") ?? "");
  const botIds = form.getAll("bot_ids").map(value => String(value));
  if (
    !["allow", "deny", "inherit"].includes(effect)
    || botIds.length < 1 || botIds.length > 100
    || botIds.some(id => !UUID.test(id))
    || new Set(botIds).size !== botIds.length
  ) {
    redirect(`/products/${productId}/edit?bot_acl_error=1#bot-access`);
  }
  const assignments = botIds.map(bot_id => ({ bot_id, effect }));
  let denied = false;
  try {
    await adminFetch(
      `/bot-catalog/products/${productId}/rules`,
      "POST", { assignments },
    );
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 401) redirect("/login?expired=1");
    denied = true;
  }
  if (denied) {
    redirect(`/products/${productId}/edit?bot_acl_error=1#bot-access`);
  }
  revalidatePath("/bots");
  revalidatePath(`/products/${productId}/edit`);
  redirect(`/products/${productId}/edit?bot_acl_saved=1#bot-access`);
}
