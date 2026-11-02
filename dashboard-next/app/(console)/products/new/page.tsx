import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/blocks/product-editor";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category } from "@/lib/types";

type Params = Promise<{ error?: string }>;

/** New products remain unpublished unless the authorized merchant opts in. */
export default async function NewProductPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const categories = await adminFetch<Category[]>("/categories");
  const params = await searchParams;
  return (
    <div>
      <PageHeading title="محصول جدید" description="ثبت اطلاعات محصول برای هر دو ربات، بدون تغییر برنامه." />
      {params.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ذخیره محصول ممکن نشد. مقادیر، SKU و محدودیت‌های نوع محصول را بررسی کنید.</p> : null}
      <ProductEditor categories={categories} />
    </div>
  );
}
