import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/blocks/product-editor";
import type { ProductAsset } from "@/components/blocks/product-media-manager";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category, Product } from "@/lib/types";

type Params = Promise<{ id: string }>;
type Search = Promise<{ error?: string }>;

/** Edit one existing product; historic paid-order snapshots remain untouched. */
export default async function EditProductPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: Search;
}) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const [product, categories, media, query] = await Promise.all([
    adminFetch<Product>(`/products/${id}`),
    adminFetch<Category[]>("/categories"),
    adminFetch<ProductAsset[]>(`/products/${id}/media`),
    searchParams,
  ]);
  return (
    <div>
      <PageHeading title={`ویرایش «${product.name}»`} description="تغییرات محصولات در هر دو ربات اعمال می‌شود؛ مبالغ سفارش‌های گذشته ثابت می‌مانند." />
      {query.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ویرایش ذخیره نشد. داده‌ها یا تکراری‌بودن SKU را بررسی کنید.</p> : null}
      <ProductEditor product={product} categories={categories} media={media} />
    </div>
  );
}
