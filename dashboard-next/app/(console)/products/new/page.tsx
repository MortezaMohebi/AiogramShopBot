import { notFound } from "next/navigation";
import { ProductEditor } from "@/components/blocks/product-editor";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Category } from "@/lib/types";
import type { UomList } from "@/lib/uoms";
import type { StoreContextSnapshot } from "@/lib/store-context";

type Params = Promise<{ error?: string; ref?: string }>;

/** New products remain unpublished unless the authorized merchant opts in. */
export default async function NewProductPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (!["superadmin", "content"].includes(staff.role)) notFound();
  const [categories, context] = await Promise.all([
    adminFetch<Category[]>("/categories"),
    adminFetch<StoreContextSnapshot>("/store-context"),
  ]);
  const units = await adminFetch<UomList>(`/stores/${context.current_store_id}/uoms`);
  const params = await searchParams;
  return (
    <div>
      <PageHeading title="محصول جدید" description="پس از ذخیرهٔ محصول، دسترسی ربات‌ها را در صفحهٔ ویرایش تعیین کنید." />
      {params.error ? <div role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
        {({
          mfa: "ابتدا احراز هویت دومرحله‌ای حساب مدیر را فعال کنید.",
          conflict: "SKU یا مشخصات یکتای محصول تکراری است.",
          validation: "مقادیر واردشده معتبر نیستند؛ نوع محصول، دسته‌بندی و فیلدهای عددی را بررسی کنید.",
          permission: "سطح دسترسی شما اجازهٔ ثبت محصول نمی‌دهد.",
          service: "سرویس مدیریت در دسترس نیست.",
          unknown: "نتیجهٔ ثبت محصول مشخص نیست. پیش از ثبت دوباره، وضعیت محصول را بررسی کنید.",
        } as Record<string, string>)[params.error] ?? "ثبت محصول انجام نشد."}
        {params.ref && /^[a-f0-9-]{36}$/i.test(params.ref) ? <details className="mt-2 text-xs">
          <summary className="cursor-pointer">اطلاعات پیگیری</summary>
          <p dir="ltr" className="mt-1 break-all font-mono">{params.ref}</p>
        </details> : null}
      </div> : null}
      <ProductEditor categories={categories.filter((item) => item.store_id === context.current_store_id)}
        uoms={units.items} storeId={context.current_store_id} />
    </div>
  );
}
