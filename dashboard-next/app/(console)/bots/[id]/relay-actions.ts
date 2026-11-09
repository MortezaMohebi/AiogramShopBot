"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";
import { needsRelayProof, relayError, relayId, relayInt, relayPassword } from "@/lib/relay-pool";
import type { DraftReceipt } from "@/components/blocks/draft-form";

function ids(form: FormData) {
  const bot = relayId(form.get("bot_id"));
  const worker = relayId(form.get("worker_id"));
  if (!bot || !worker) redirect("/bots?error=validation");
  return { bot, worker, route: `/bots/${bot}/relay/${worker}`, api: `/bot-registry/${bot}/relay-routes/${worker}` };
}

function refresh(bot: string, route: string) {
  revalidatePath("/relay-workers");
  revalidatePath(`/bots/${bot}`);
  revalidatePath(route);
}

function fail(error: unknown, route: string): never {
  if (error instanceof ApiError && error.status === 401 && error.code !== "invalid_credentials") redirect("/login?expired=1");
  redirect(`${route}?error=${relayError(error)}`);
}

export async function assignRelayRoute(form: FormData) {
  const { bot, worker, route } = ids(form);
  const priority = relayInt(form.get("priority"), 1000);
  if (!priority) redirect(`/bots/${bot}?relay_error=validation#bot-relays`);
  try {
    await adminFetch(`/bot-registry/${bot}/relay-routes`, "POST", { worker_id: worker, priority });
  } catch (error) {
    if (needsRelayProof(error)) return { reauthenticate: true } as const;
    if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1");
    redirect(`/bots/${bot}?relay_error=${relayError(error)}#bot-relays`);
  }
  refresh(bot, route);
  redirect(`${route}?saved=assigned`);
}

export async function saveRelayPriority(form: FormData): Promise<DraftReceipt> {
  const { bot, worker, route } = ids(form);
  const priority = relayInt(form.get("priority"), 1000);
  const expected_version = relayInt(form.get("expected_version"));
  if (!priority || !expected_version) return { ok: false, code: "validation" };
  try {
    await adminFetch(`/bot-registry/${bot}/relay-routes`, "POST", { worker_id: worker, priority, expected_version });
  } catch (error) {
    if (needsRelayProof(error)) return { ok: false, code: "reauthentication_required" };
    if (error instanceof ApiError && error.status === 401) return { ok: false, code: "session_expired" };
    return { ok: false, message: relayError(error, true) };
  }
  refresh(bot, route);
  return { ok: true, data: null };
}

export async function stageRelayCredential(form: FormData) {
  const { bot, route, api } = ids(form);
  const secret = String(form.get("secret") ?? "");
  const expected_version = relayInt(form.get("expected_version"));
  if (!expected_version) redirect(`${route}?error=validation`);
  if (!/^[!-~]{32,256}$/.test(secret)) redirect(`${route}?error=invalid_worker_secret`);
  try {
    await adminFetch(`${api}/credentials/stage`, "POST", { secret, expected_version });
  } catch (error) {
    if (needsRelayProof(error)) return { reauthenticate: true } as const;
    fail(error, route);
  }
  refresh(bot, route);
  redirect(`${route}?saved=staged`);
}

async function apply(form: FormData, operation: "activate" | "pause" | "remove" | "revoke"): Promise<void> {
  const { bot, route, api } = ids(form);
  const current_password = relayPassword(form.get("current_password"));
  const expected_version = relayInt(form.get("expected_version"));
  const credential_version = relayInt(form.get("credential_version"), 999_999_999);
  if (!current_password || (operation === "revoke" ? !credential_version :
    !expected_version || (operation === "activate" && !credential_version))) {
    redirect(`${route}?error=validation`);
  }
  try {
    if (operation === "remove") {
      await adminFetch(`${api}/remove`, "POST", { expected_version, current_password });
    } else if (operation === "revoke") {
      await adminFetch(`${api}/credentials/revoke`, "POST", { version: credential_version, current_password });
    } else {
      await adminFetch(`${api}/${operation}`, "POST", {
        expected_version, current_password, ...(operation === "activate" && { credential_version }),
      }, operation === "activate" ? 45_000 : undefined);
    }
  } catch (error) {
    fail(error, route);
  }
  refresh(bot, route);
  redirect(operation === "remove" ? `/bots/${bot}?relay_saved=removed#bot-relays` : `${route}?saved=${operation}`);
}

export async function activateRelayRoute(form: FormData): Promise<void> {
  await apply(form, "activate");
}

export async function pauseRelayRoute(form: FormData): Promise<void> {
  await apply(form, "pause");
}

export async function removeRelayRoute(form: FormData): Promise<void> {
  await apply(form, "remove");
}

export async function revokeRelayCredential(form: FormData): Promise<void> {
  await apply(form, "revoke");
}
