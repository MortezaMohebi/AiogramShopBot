"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

const safe = /^[a-z][a-z0-9-]{2,63}$/;

function errorCode(error: unknown): string {
  if (!(error instanceof ApiError)) throw error;
  if (error.status === 401) redirect("/login?expired=1");
  if (error.status === 428) return "reauth";
  return error.status === 409 ? "conflict" : "save";
}

/** Register a draft bot with no active Webhook, Telegram or Bale receiver. */
export async function createBot(form: FormData): Promise<void> {
  const store_id = String(form.get("store_id") ?? "");
  const platform = String(form.get("platform") ?? "");
  const slug = String(form.get("slug") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  if (
    !/^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(store_id) ||
    !["telegram", "bale"].includes(platform) ||
    !safe.test(slug) || !name || name.length > 160
  ) {
    redirect("/bots?error=validation");
  }
  let result: { ok: boolean; bot: { id: string } };
  try {
    result = await adminFetch("/bot-registry", "POST", {
      store_id, platform, slug, name,
    });
  } catch (error) {
    redirect(`/bots?error=${errorCode(error)}`);
  }
  revalidatePath("/bots");
  redirect(`/bots/${result.bot.id}?saved=created`);
}
