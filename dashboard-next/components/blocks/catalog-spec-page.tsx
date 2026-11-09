import Link from "next/link";
import { notFound } from "next/navigation";
import { CatalogSpecManager } from "@/components/blocks/catalog-spec-manager";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { CatalogKind } from "@/lib/catalog-specs";
import type { StoreContextSnapshot } from "@/lib/store-context";

export async function CatalogSpecPage({ kind }: { kind: CatalogKind }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const context = await adminFetch<StoreContextSnapshot>("/store-context");
  const storeId = context.current_store_id;
  const attributes = kind === "attributes";
  return <div className="space-y-4">
    <PageHeading title={attributes ? "ویژگی‌های محصول" : "مقدارهای ویژگی"}
      description={attributes ? "ویژگی‌ها را برای فروشگاه تعریف کنید و در محصولات دوباره از آن‌ها استفاده کنید."
        : "مقدارهای هر ویژگی را تعریف کنید تا در جدول محصول به شکل تگ انتخاب شوند."} />
    <Link href={attributes ? "/product-attribute-values" : "/product-attributes"} className="inline-block text-sm text-primary hover:underline">
      {attributes ? "مدیریت مقدارهای ویژگی" : "مدیریت ویژگی‌ها"}
    </Link>
    <CatalogSpecManager key={`${storeId}-${kind}`} kind={kind} storeId={storeId} />
  </div>;
}
