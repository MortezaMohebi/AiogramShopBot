import { notFound } from "next/navigation";
import { saveCategory } from "@/app/(console)/categories/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CategoryParentPicker } from "@/components/blocks/category-parent-picker";
import { categoryParentOptions } from "@/lib/category-tree";
import { CategoryOrderTable } from "@/components/blocks/category-order-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BulkSelectCheckbox, BulkUnpublishSelection } from "@/components/blocks/bulk-unpublish-selection";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category } from "@/lib/types";
import type { StoreContextSnapshot } from "@/lib/store-context";

type Params = Promise<{ error?: string; saved?: string }>;

/** Merchant-controlled categories with no dynamic menu-builder overhead. */
export default async function CategoriesPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const [staff, categories, context] = await Promise.all([
    currentStaff(),
    adminFetch<(Category & { store_id: string })[]>("/categories"),
    adminFetch<StoreContextSnapshot>("/store-context"),
  ]);
  const edit = ["superadmin", "content"].includes(staff.role);
  if (!["superadmin", "content", "sales", "viewer"].includes(staff.role)) notFound();

  return (
    <div>
      <PageHeading title="دسته‌بندی‌ها" />
      {params.error ? <p role="alert" className="mb-5 rounded-lg bg-destructive/10 p-4 text-sm text-destructive">دسته‌بندی ذخیره نشد. نام و دسته‌بندی والد را بررسی کنید.</p> : null}
      {params.saved ? <p role="status" className="mb-5 rounded-lg bg-accent p-4 text-sm text-accent-foreground">دسته‌بندی ذخیره شد.</p> : null}
      <div className="grid items-start gap-5 xl:grid-cols-[1fr_1.6fr]">
        {edit ? (
          <Card>
            <CardHeader><CardTitle>افزودن دسته‌بندی</CardTitle></CardHeader>
            <CardContent>
              <form action={saveCategory} className="space-y-4">
                <label className="block space-y-2 text-sm font-medium">نام دسته‌بندی
                  <Input name="name" required maxLength={255} placeholder="نام قابل نمایش در ربات" />
                </label>
                <CategoryParentPicker options={categoryParentOptions(categories.filter(item =>
                  item.store_id === context.current_store_id))} />
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-primary" name="is_published" /> انتشار
                </label>
                <Button type="submit" size="sm">افزودن دسته‌بندی</Button>
              </form>
            </CardContent>
          </Card>
        ) : null}
        <Card>
          <CardHeader><CardTitle>دسته‌بندی‌های موجود</CardTitle></CardHeader>
          <CardContent>
            <BulkUnpublishSelection entity="categories" enabled={edit}
              eligible={categories.filter((category) => category.is_published && category.store_id === context.current_store_id).map((category) => category.id)}>
            {edit ? <label className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
              <BulkSelectCheckbox all /> انتخاب همهٔ دسته‌بندی‌های منتشرشده
            </label> : null}
            <CategoryOrderTable categories={categories} storeId={context.current_store_id} edit={edit} />
            </BulkUnpublishSelection>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
