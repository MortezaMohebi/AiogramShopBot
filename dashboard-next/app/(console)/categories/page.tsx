import { notFound } from "next/navigation";
import { saveCategory } from "@/app/(console)/categories/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
      <PageHeading title="دسته‌بندی‌ها" description="نام، ترتیب و انتشار دسته‌بندی‌ها از دیتابیس مدیریت می‌شود؛ منوی اصلی ربات ثابت باقی می‌ماند." />
      {params.error ? <p role="alert" className="mb-5 rounded-lg bg-destructive/10 p-4 text-sm text-destructive">عملیات ذخیره نشد؛ احتمالاً نام دسته‌بندی تکراری یا مقدار نامعتبر است.</p> : null}
      {params.saved ? <p role="status" className="mb-5 rounded-lg bg-accent p-4 text-sm text-accent-foreground">تغییرات دسته‌بندی ثبت شد.</p> : null}
      <div className="grid items-start gap-5 xl:grid-cols-[1fr_1.6fr]">
        {edit ? (
          <Card>
            <CardHeader><CardTitle>افزودن دسته‌بندی</CardTitle></CardHeader>
            <CardContent>
              <form action={saveCategory} className="space-y-4">
                <label className="block space-y-2 text-sm font-medium">نام دسته‌بندی
                  <Input name="name" required maxLength={255} placeholder="نام قابل نمایش در ربات" />
                </label>
                <label className="block space-y-2 text-sm font-medium">ترتیب
                  <Input name="position" type="number" defaultValue={0} min={0} max={1000000} required />
                </label>
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
          <CardContent className="divide-y divide-border">
            {categories.map((category) => (
              <details key={category.id} className="group py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
                  <span className="font-medium">{category.name}</span>
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
                    <Input name="name" defaultValue={category.name} required maxLength={255} aria-label="نام دسته‌بندی" />
                    <Input type="number" name="position" defaultValue={category.position} min={0} max={1000000} aria-label="ترتیب" />
                    <label className="flex items-center gap-2 text-xs">
                      <input type="checkbox" name="is_published" defaultChecked={category.is_published} className="accent-primary" /> فعال
                    </label>
                    <Button size="sm" type="submit">ثبت تغییر</Button>
                  </form>
                ) : null}
              </details>
            ))}
            {categories.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">دسته‌بندی‌ای تعریف نشده است.</p> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
