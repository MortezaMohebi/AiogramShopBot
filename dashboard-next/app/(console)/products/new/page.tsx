import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/blocks/product-editor";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category } from "@/lib/types";

type Params = Promise<{ error?: string; ref?: string }>;

/** New products remain unpublished unless the authorized merchant opts in. */
export default async function NewProductPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const categories = await adminFetch<Category[]>("/categories");
  const params = await searchParams;
  return (
    <div>
      <PageHeading title="محصول جدید" description="محصول ابتدا در کاتالوگ مرکزی ثبت می‌شود؛ دسترسی بات‌ها را پس از ثبت در فرم ویرایش تعیین کنید." />
      {params.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
        {({
          mfa: "ابتدا احراز هویت دومرحله‌ای حساب مدیر را فعال کنید.",
          conflict: "SKU یا مشخصات یکتای محصول تکراری است.",
          validation: "مقادیر واردشده معتبر نیستند؛ نوع محصول، دسته‌بندی و فیلدهای عددی را بررسی کنید.",
          permission: "سطح دسترسی شما اجازهٔ ثبت محصول نمی‌دهد.",
          service: "ارتباط با سرویس مدیریت یا پایگاه داده برقرار نشد.",
          unknown: "ثبت محصول انجام نشد. شمارهٔ پیگیری را برای بررسی نگه دارید.",
        } as Record<string, string>)[params.error] ?? "ثبت محصول انجام نشد."}
        {params.ref && /^[a-f0-9-]{36}$/i.test(params.ref) ? <span className="mt-2 block font-mono text-xs" dir="ltr">Request ID: {params.ref}</span> : null}
      </p> : null}
      <ProductEditor categories={categories} />
    </div>
  );
}
