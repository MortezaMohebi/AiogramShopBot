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
  let errorCode: string | null = null;
  let requestId: string | null = null;
  let savedId: number | null = null;
  try {
    const result = await adminFetch<{ id: number }>(
      id ? `/products/${encodeURIComponent(id)}` : "/products",
      id ? "PATCH" : "POST",
      payload,
    );
    savedId = result.id;
  } catch (error) {
    // Only allowlisted reason codes and correlation IDs reach browser URLs.
    if (!(error instanceof ApiError)) throw error;
    errorCode = error.code === "mfa_enrollment_required" ? "mfa" :
      error.status === 409 ? "conflict" :
      error.status === 422 ? "validation" :
      error.status === 403 ? "permission" :
      error.status === 503 || error.status === 504 ? "service" : "unknown";
    requestId = error.requestId && /^[a-f0-9-]{36}$/i.test(error.requestId)
      ? error.requestId : null;
  }
  if (errorCode) {
    const query = new URLSearchParams({ error: errorCode });
    if (requestId) query.set("ref", requestId);
    redirect(id ? `/products/${id}/edit?${query}` : `/products/new?${query}`);
  }
  revalidatePath("/products");
  revalidatePath("/dashboard");
  // Keep the editor open so newly created products can receive their media.
  redirect(savedId && Number.isSafeInteger(savedId) && savedId > 0 ? `/products/${savedId}/edit?saved=1` : "/products?saved=1");
}
