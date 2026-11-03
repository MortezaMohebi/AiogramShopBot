import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/blocks/product-editor";
import type { ProductAsset } from "@/components/blocks/product-media-manager";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category, Product } from "@/lib/types";

type Params = Promise<{ id: string }>;
type Search = Promise<{ error?: string; saved?: string; ref?: string }>;

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
      {query.saved ? <p role="status" className="mb-4 rounded-lg border bg-muted p-3 text-sm">محصول ذخیره شد. اکنون می‌توانید رسانه‌های آن را اضافه یا ویرایش کنید.</p> : null}
      {query.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
        {({
          mfa: "ابتدا احراز هویت دومرحله‌ای حساب مدیر را فعال کنید.",
          conflict: "کد SKU یا مشخصات یکتای محصول تکراری است.",
          validation: "داده‌های محصول معتبر نیستند؛ نوع محصول و فیلدهای عددی را بررسی کنید.",
          permission: "برای ویرایش محصول اجازه ندارید.",
          service: "دسترسی به API یا پایگاه داده برقرار نشد.",
          unknown: "ویرایش محصول انجام نشد؛ شمارهٔ پیگیری را بررسی کنید.",
        } as Record<string, string>)[query.error] ?? "ویرایش محصول انجام نشد."}
        {query.ref && /^[a-f0-9-]{36}$/i.test(query.ref) ? <span className="mt-2 block font-mono text-xs" dir="ltr">Request ID: {query.ref}</span> : null}
      </p> : null}
      <ProductEditor product={product} categories={categories} media={media} />
    </div>
  );
}
