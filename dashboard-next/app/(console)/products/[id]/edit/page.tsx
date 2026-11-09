import { notFound } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ProductEditor } from "@/components/blocks/product-editor";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { productListSearch, type ProductNavigation } from "@/lib/product-list-context";
import type { Category, Product } from "@/lib/types";
import type { ProductFile } from "@/components/blocks/product-media-panel";
import type { ProductBotCatalogList } from "@/lib/bot-catalog-acl";
import type { UomList } from "@/lib/uoms";

type Params = Promise<{ id: string }>;
type Search = Promise<{
  error?: string;
  list_search?: string | string[];
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
  const listSearch = productListSearch(query.list_search);
  const listContext = new URLSearchParams({ list_search: listSearch });
  const botQuery = (query.bot_q ?? "").trim().slice(0, 100);
  const botPage = Math.min(
    100000, Math.max(1, Number.parseInt(query.bot_page ?? "1", 10) || 1),
  );
  const aclSearch = new URLSearchParams({
    q: botQuery, page: String(botPage), page_size: "25",
  });
  const [product, categories, media, botAccess] = await Promise.all([
    adminFetch<Product & { navigation: ProductNavigation | null }>(`/products/${id}?${listContext}`),
    adminFetch<Category[]>("/categories"),
    adminFetch<{ items: ProductFile[] }>(`/products/${id}/media`),
    staff.role === "superadmin"
      ? adminFetch<ProductBotCatalogList>(
          `/bot-catalog/products/${id}?${aclSearch}`,
        )
      : Promise.resolve(undefined),
  ]);
  const units = await adminFetch<UomList>(`/stores/${product.store_id}/uoms`);
  return (
    <div>
      <ProductEditor key={product.id}
        list={{ navigation: product.navigation, search: listSearch }}
        product={product} categories={categories.filter((item) => item.store_id === product.store_id)}
        uoms={units.items} storeId={product.store_id}
        media={media.items}
        botAccess={botAccess} botAccessQuery={botQuery}
        botAccessSaved={query.bot_acl_saved === "1"}
        botAccessError={query.bot_acl_error === "1"}
      >
        {product.product_type === "digital" ? <div className="mb-4">
          <Button variant="outline" asChild>
            <Link href={`/products/${product.id}/digital`}>فایل و لایسنس محصول</Link>
          </Button>
        </div> : null}
        {query.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ذخیرهٔ ویرایش‌ها تأیید نشد. پیش از تلاش دوباره، وضعیت محصول را بررسی کنید.</p> : null}
      </ProductEditor>
    </div>
  );
}
