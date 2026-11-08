"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { adminFetch } from "@/lib/bridge";

/** Save a category in the original PostgreSQL model used by both bots. */
export async function saveCategory(form: FormData) {
  const id = String(form.get("id") ?? "").trim();
  const name = String(form.get("name") ?? "").trim();
  const is_published = form.has("is_published");
  // Creation allocates the next position in PostgreSQL; only edits accept one.
  const payload = id
    ? { name, position: Number(form.get("position") ?? 0), is_published }
    : { name, is_published };
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
