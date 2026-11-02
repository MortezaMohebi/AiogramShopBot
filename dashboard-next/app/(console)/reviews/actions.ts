"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

function idOf(form: FormData): string {
  const id = String(form.get("id") ?? "");
  if (!/^[1-9]\d*$/.test(id)) redirect("/reviews?error=id");
  return id;
}

/** Editing the customer's testimonial automatically revokes prior approval. */
export async function editReview(form: FormData) {
  const id = idOf(form);
  let failed = false;
  try {
    await adminFetch(`/testimonials/${id}`, "PATCH", {
      text: String(form.get("text") ?? "").trim(),
      position: Number(form.get("position")),
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/reviews?error=edit");
  revalidatePath("/reviews");
  redirect("/reviews?saved=1");
}

/** Approve only after the operator has reviewed the underlying evidence. */
export async function moderateReview(form: FormData) {
  const id = idOf(form);
  const approved = String(form.get("approve"));
  if (!["true", "false"].includes(approved)) redirect("/reviews?error=id");
  let failed = false;
  try {
    await adminFetch(`/testimonials/${id}`, "PATCH", {
      is_approved: approved === "true",
    });
  } catch {
    failed = true;
  }
  if (failed) redirect("/reviews?error=approve");
  revalidatePath("/reviews");
  redirect("/reviews?saved=1");
}

/** Remove only an unapproved testimonial with deliberate operator consent. */
export async function deleteReview(form: FormData) {
  const id = idOf(form);
  if (String(form.get("confirmation")) !== "DELETE_DRAFT_REVIEW") {
    redirect("/reviews?error=confirmation");
  }
  let failed = false;
  try {
    await adminFetch(`/testimonials/${id}`, "DELETE");
  } catch {
    failed = true;
  }
  if (failed) redirect("/reviews?error=delete");
  revalidatePath("/reviews");
  redirect("/reviews?saved=1");
}
