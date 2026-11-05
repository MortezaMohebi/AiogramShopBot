import { adminFetch } from "@/lib/bridge";
import { workflowRecord } from "@/lib/workflows/server";
import { PageHeading } from "@/components/blocks/page-heading";
import { CreateWorkflowForm } from "@/components/workflows/create-form";
import type { Catalog } from "@/lib/workflows/types";
export default async function NewWorkflow({
  searchParams,
}: {
  searchParams: Promise<{ source?: string }>;
}) {
  const { source } = await searchParams;
  const catalog = await adminFetch<Catalog>("/workflows/catalog");
  const original = source ? await workflowRecord(source) : undefined;
  return (
    <>
      <PageHeading
        title={source ? "کپی فرایند" : "فرایند جدید"}
        description="نام و کلید پایدار را انتخاب کنید. تعریف فرایند و چیدمان آن جداگانه ذخیره می‌شوند."
      />
      {catalog.can_write &&
      (!original || original.store_id === catalog.store_id) ? (
        <CreateWorkflowForm source={original} />
      ) : (
        <p className="rounded-xl border p-6 text-sm">
          ایجاد فرایند به دسترسی ویرایش در فروشگاه جاری نیاز دارد.
        </p>
      )}
    </>
  );
}
