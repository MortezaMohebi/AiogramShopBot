import { Suspense } from "react";
import { ProductsResults } from "@/components/data/products";
import { TableSkeleton } from "@/components/data/skeletons";
import Link from "next/link";
import { Plus, Search } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { currentStaff } from "@/lib/bridge";

type Params = Promise<{ page?: string; search?: string; saved?: string }>;

/** Product catalogue block with server pagination, actual SKU and stock. */
export default async function ProductsPage({ searchParams }: { searchParams: Params }) {
  const q = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(q.page ?? "1", 10) || 1));
  const search = (q.search ?? "").slice(0, 100);
  const staff = await currentStaff();
  const canEdit = staff.role === "superadmin" || staff.role === "content";

  return (
    <div>
      <PageHeading
        title="محصولات"
        action={canEdit ? <Button asChild><Link href="/products/new"><Plus /> محصول جدید</Link></Button> : undefined}
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href="/data-models/products">جست‌وجوی پیشرفته و ورود و خروج داده</Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link href="/uoms">واحدهای اندازه‌گیری</Link>
        </Button>
      </div>
      {q.saved ? <p role="status" className="mb-4 rounded-lg bg-accent px-4 py-3 text-sm text-accent-foreground">محصول ذخیره شد.</p> : null}
      <Card>
        <CardContent className="pt-5">
          <form method="get" className="mb-5 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 space-y-2 text-sm">
              <span className="font-medium">جستجو در محصول و SKU</span>
              <Input name="search" maxLength={100} placeholder="نام یا کد کالا..." defaultValue={search} />
            </label>
            <Button type="submit" variant="outline"><Search /> جستجو</Button>
          </form>
          <Suspense key={JSON.stringify([page, search])} fallback={<TableSkeleton label="در حال دریافت محصولات…" />}>
            <ProductsResults page={page} search={search} canEdit={canEdit} />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}
