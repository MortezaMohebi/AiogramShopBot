import { notFound } from "next/navigation";
import { saveCategory } from "@/app/(console)/categories/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { BulkSelectCheckbox, BulkUnpublishSelection } from "@/components/blocks/bulk-unpublish-selection";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category } from "@/lib/types";

type Params = Promise<{ error?: string; saved?: string }>;

/** Merchant-controlled categories with no dynamic menu-builder overhead. */
export default async function CategoriesPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const [staff, categories] = await Promise.all([
    currentStaff(),
    adminFetch<Category[]>("/categories"),
  ]);
  const edit = ["superadmin", "content"].includes(staff.role);
  if (!["superadmin", "content", "sales", "viewer"].includes(staff.role)) notFound();

  return (
    <div>
      <PageHeading title="دسته‌بندی‌ها" />
      {params.error ? <p role="alert" className="mb-5 rounded-lg bg-destructive/10 p-4 text-sm text-destructive">دسته‌بندی ذخیره نشد. نام و ترتیب نمایش را بررسی کنید.</p> : null}
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
                <p className="text-sm text-muted-foreground">ترتیب نمایش خودکار تعیین می‌شود و پس از ایجاد قابل ویرایش است.</p>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="size-4 accent-primary" name="is_published" /> انتشار
                </label>
                <Button type="submit" className="w-full">ذخیره دسته‌بندی</Button>
              </form>
            </CardContent>
          </Card>
        ) : null}
        <Card>
          <CardHeader><CardTitle>دسته‌بندی‌های موجود</CardTitle></CardHeader>
          <CardContent>
            <BulkUnpublishSelection entity="categories" enabled={edit}
              eligible={categories.filter((category) => category.is_published).map((category) => category.id)}>
            {edit ? <label className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
              <BulkSelectCheckbox all /> انتخاب همهٔ دسته‌بندی‌های منتشرشده
            </label> : null}
            <div className="divide-y divide-border">
            {categories.map((category) => (
              <details key={category.id} className="group py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
                  <span className="flex items-center gap-3 font-medium">
                    {edit ? <BulkSelectCheckbox id={category.id} /> : null}
                    {category.name}
                  </span>
                  <div className="flex items-center gap-2">
                    <Badge tone={category.is_published ? "success" : "neutral"}>
                      {category.is_published ? "منتشرشده" : "پیش‌نویس"}
                    </Badge>
                    <span className="text-xs text-muted-foreground">#{category.id}</span>
                  </div>
                </summary>
                {edit ? (
                  <form action={saveCategory} className="mt-4 grid gap-3 rounded-lg bg-muted/50 p-4 sm:grid-cols-[1fr_90px_auto]">
                    <input type="hidden" name="id" value={category.id} />
                    <label className="block space-y-2 text-sm">نام دسته‌بندی
                      <Input name="name" defaultValue={category.name} required maxLength={255} />
                    </label>
                    <label className="block space-y-2 text-sm">ترتیب
                      <Input type="number" name="position" defaultValue={category.position} min={0} max={1000000} dir="ltr" />
                    </label>
                    <label className="flex items-center gap-2 text-xs">
                      <input type="checkbox" name="is_published" defaultChecked={category.is_published} className="accent-primary" /> انتشار
                    </label>
                    <Button size="sm" type="submit">ذخیرهٔ تغییرات</Button>
                  </form>
                ) : null}
              </details>
            ))}
            {categories.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">هنوز دسته‌بندی‌ای تعریف نشده است.</p> : null}
            </div>
            </BulkUnpublishSelection>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
