import { notFound } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ProductEditor } from "@/components/blocks/product-editor";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category, Product } from "@/lib/types";
import type { ProductFile } from "@/components/blocks/product-media-panel";
import type { ProductBotCatalogList } from "@/lib/bot-catalog-acl";
import type { UomList } from "@/lib/uoms";

type Params = Promise<{ id: string }>;
type Search = Promise<{
  error?: string;
  bot_q?: string;
  bot_page?: string;
  bot_acl_saved?: string;
  bot_acl_error?: string;
}>;

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
  const query = await searchParams;
  const botQuery = (query.bot_q ?? "").trim().slice(0, 100);
  const botPage = Math.min(
    100000, Math.max(1, Number.parseInt(query.bot_page ?? "1", 10) || 1),
  );
  const aclSearch = new URLSearchParams({
    q: botQuery, page: String(botPage), page_size: "25",
  });
  const [product, categories, media, botAccess] = await Promise.all([
    adminFetch<Product>(`/products/${id}`),
    adminFetch<Category[]>("/categories"),
    adminFetch<{ items: ProductFile[] }>(`/products/${id}/media`),
    staff.role === "superadmin"
      ? adminFetch<ProductBotCatalogList>(
          `/bot-catalog/products/${id}?${aclSearch}`,
        )
      : Promise.resolve(undefined),
  ]);
  const units = await adminFetch<UomList>(
    `/stores/${product.store_id}/uoms`,
  );
  return (
    <div>
      <PageHeading title={`ویرایش «${product.name}»`} description="دسترسی هر ربات جداگانه تعیین می‌شود. این تغییرات، مبالغ سفارش‌های گذشته را تغییر نمی‌دهند." />
      {product.product_type === "digital" ? <div className="mb-4">
        <Button variant="outline" asChild>
          <Link href={`/products/${product.id}/digital`}>فایل و لایسنس محصول</Link>
        </Button>
      </div> : null}
      {query.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ویرایش ذخیره نشد. داده‌ها یا تکراری‌بودن SKU را بررسی کنید.</p> : null}
      <ProductEditor
        product={product} categories={categories} uoms={units.items}
        media={media.items}
        botAccess={botAccess} botAccessQuery={botQuery}
        botAccessSaved={query.bot_acl_saved === "1"}
        botAccessError={query.bot_acl_error === "1"}
      />
    </div>
  );
}
