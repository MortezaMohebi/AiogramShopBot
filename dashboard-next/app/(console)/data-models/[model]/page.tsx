import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { ModelDataWorkbench } from "@/components/blocks/model-data-workbench";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { ModelMetadata, ModelName } from "@/lib/model-data";

type Params = Promise<{ model: string }>;
const SUPPORTED = new Set(["products", "customers", "orders"]);

const backlinks: Record<ModelName, { title: string; href: string }> = {
  products: { title: "فهرست محصولات", href: "/products" },
  customers: { title: "مشتریان فروشگاه", href: "/store-customers" },
  orders: { title: "سفارش‌ها", href: "/orders" },
};

/** All model-dependent controls derive from backend ModelRegistry metadata. */
export default async function DataModelPage({ params }: { params: Params }) {
  const { model } = await params;
  if (!SUPPORTED.has(model)) notFound();
  const name = model as ModelName;
  const metadata = await adminFetch<ModelMetadata>(`/data-models/${name}`);

  return <div className="space-y-6">
    <Button asChild size="sm" variant="outline">
      <Link href={backlinks[name].href}>{backlinks[name].title}</Link>
    </Button>
    <PageHeading title={`مدیریت داده: ${metadata.label}`}
      description="داده‌ها را جست‌وجو و گروه‌بندی کنید یا فایل خروجی بگیرید." />
    <ModelDataWorkbench metadata={metadata} />
  </div>;
}
