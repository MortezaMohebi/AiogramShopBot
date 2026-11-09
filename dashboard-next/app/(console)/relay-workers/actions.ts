"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";
import { relayError, relayId, relayInt, relayPassword, needsRelayProof } from "@/lib/relay-pool";
import type { DraftReceipt } from "@/components/blocks/draft-form";

function fields(form: FormData) {
  const slug = String(form.get("slug") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  const max_rps = relayInt(form.get("max_rps"), 20);
  const max_inflight = relayInt(form.get("max_inflight"), 50);
  if (!/^[a-z][a-z0-9-]{2,63}$/.test(slug) || !name || name.length > 160 || !max_rps || !max_inflight) return null;
  return { slug, name, max_rps, max_inflight };
}

export async function createRelayWorker(form: FormData) {
  const data = fields(form);
  const origin = String(form.get("origin") ?? "").trim();
  if (!data || origin.length < 8 || origin.length > 300) redirect("/relay-workers/new?error=validation");
  let worker: { id: string };
  try {
    worker = await adminFetch("/relay-workers", "POST", { ...data, origin });
  } catch (error) {
    if (needsRelayProof(error)) return { reauthenticate: true } as const;
    if (error instanceof ApiError && error.status === 401) redirect("/login?expired=1");
    redirect(`/relay-workers/new?error=${relayError(error)}`);
  }
  revalidatePath("/relay-workers");
  redirect(`/relay-workers/${worker.id}?saved=created`);
}

export async function saveRelayWorker(form: FormData): Promise<DraftReceipt> {
  const id = relayId(form.get("worker_id"));
  const expected_version = relayInt(form.get("expected_version"));
  const data = fields(form);
  if (!id || !expected_version || !data) return { ok: false, code: "validation" };
  try {
    await adminFetch(`/relay-workers/${id}`, "PATCH", { ...data, expected_version });
  } catch (error) {
    if (needsRelayProof(error)) return { ok: false, code: "reauthentication_required" };
    if (error instanceof ApiError && error.code === "configuration_changed") return { ok: false, code: "conflict" };
    if (error instanceof ApiError && error.status === 401) return { ok: false, code: "session_expired" };
    return { ok: false, message: relayError(error, true) };
  }
  revalidatePath("/relay-workers");
  revalidatePath(`/relay-workers/${id}`);
  return { ok: true, data: null };
}

async function apply(form: FormData, operation: "state" | "origin" | "remove"): Promise<void> {
  const id = relayId(form.get("worker_id"));
  if (!id) redirect("/relay-workers");
  const path = `/relay-workers/${id}`;
  const expected_version = relayInt(form.get("expected_version"));
  const current_password = relayPassword(form.get("current_password"));
  if (!expected_version || !current_password) redirect(`${path}?error=validation`);
  const proof = { expected_version, current_password };
  try {
    if (operation === "state") {
      const state = String(form.get("state") ?? "");
      if (!["active", "paused", "disabled"].includes(state)) redirect(`${path}?error=validation`);
      await adminFetch(`${path}/state`, "POST", { ...proof, state });
    } else if (operation === "origin") {
      const data = fields(form);
      const origin = String(form.get("origin") ?? "").trim();
      if (!data || origin.length < 8 || origin.length > 300) redirect(`${path}?error=validation`);
      await adminFetch(path, "PATCH", { ...proof, ...data, origin });
    } else {
      await adminFetch(`${path}/remove`, "POST", proof);
    }
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (error.status === 401 && error.code !== "invalid_credentials") redirect("/login?expired=1");
    redirect(`${path}?error=${relayError(error)}`);
  }
  revalidatePath("/relay-workers");
  revalidatePath("/bots/[id]", "page");
  redirect(operation === "remove" ? "/relay-workers?saved=removed" : `${path}?saved=${operation}`);
}

export async function setRelayWorkerState(form: FormData): Promise<void> {
  await apply(form, "state");
}

export async function changeRelayOrigin(form: FormData): Promise<void> {
  await apply(form, "origin");
}

export async function removeRelayWorker(form: FormData): Promise<void> {
  await apply(form, "remove");
}
