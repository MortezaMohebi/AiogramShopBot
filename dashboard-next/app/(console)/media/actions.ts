"use server";

import { revalidatePath } from "next/cache";
import { saveDraftMutation } from "@/lib/draft-mutation";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

function idFrom(form: FormData): string {
  const id = String(form.get("id") ?? "");
  if (!/^[1-9]\d*$/.test(id)) redirect("/media?error=id");
  return id;
}

/** Edit metadata separately from publication so new captions are reviewed. */
export async function editMedia(form: FormData) {
  const id = String(form.get("id") ?? "");
  if (!/^[1-9]\d*$/.test(id)) return { ok: false, code: "validation" } as const;
  return saveDraftMutation(`/media/${id}`, "PATCH", {
    caption: String(form.get("caption") ?? "").trim(),
    position: Number(form.get("position")),
  }, "/media");
}

/** Explicitly approve or revoke a private product asset. */
export async function moderateMedia(form: FormData) {
  const id = idFrom(form);
  const flag = String(form.get("publish"));
  if (flag !== "true" && flag !== "false") redirect("/media?error=id");
  let failed = false;
  try {
    await adminFetch(`/media/${id}`, "PATCH", { is_published: flag === "true" });
  } catch {
    failed = true;
  }
  if (failed) redirect("/media?error=moderation");
  revalidatePath("/media");
  redirect("/media?saved=1");
}

/** Destroy only unpublished files after a deliberate typed confirmation. */
export async function deleteMedia(form: FormData) {
  const id = idFrom(form);
  if (String(form.get("confirmation")) !== "DELETE_DRAFT_MEDIA") {
    redirect("/media?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/media/${id}`, "DELETE");
  } catch {
    failed = true;
  }
  if (failed) redirect("/media?error=delete");
  revalidatePath("/media");
  redirect("/media?saved=1");
}
