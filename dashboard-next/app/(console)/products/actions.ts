"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { ApiError, adminFetch } from "@/lib/bridge";

function formString(form: FormData, name: string): string {
  return String(form.get(name) ?? "").trim();
}

/** Reuse Python's authoritative catalogue models and stock validations. */
export async function saveProduct(form: FormData) {
  const id = formString(form, "id");
  const productType = formString(form, "product_type");
  const category = formString(form, "category_id");
  const rawStars = formString(form, "price_stars");
  const payload = {
    sku: formString(form, "sku"),
    name: formString(form, "name"),
    description: formString(form, "description"),
    category_id: category ? Number(category) : null,
    price_irr: formString(form, "price_irr"),
    price_stars: rawStars ? Number(rawStars) : null,
    stock_quantity: Number(formString(form, "stock_quantity")),
    position: Number(formString(form, "position")),
    product_type: productType,
    requires_shipping: productType === "digital" ? false : form.has("requires_shipping"),
    is_published: form.has("is_published"),
  };
  let failed = false;
  try {
    await adminFetch<{ id: number }>(
      id ? `/products/${encodeURIComponent(id)}` : "/products",
      id ? "PATCH" : "POST",
      payload,
    );
  } catch (error) {
    // Do not echo raw server exceptions or secret values into a URL.
    failed = true;
    if (!(error instanceof ApiError)) throw error;
  }
  if (failed) redirect(id ? `/products/${id}/edit?error=1` : "/products/new?error=1");
  revalidatePath("/products");
  revalidatePath("/dashboard");
  redirect("/products?saved=1");
}
