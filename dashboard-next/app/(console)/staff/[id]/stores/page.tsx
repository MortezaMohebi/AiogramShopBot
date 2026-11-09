import { PasswordActionForm } from "@/components/blocks/password-action-form";
import Link from "next/link";
import { notFound } from "next/navigation";
import { StaffStoreTable } from "@/components/blocks/staff-store-table";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StaffStorePermissions } from "@/lib/store-context";
import { saveStaffStoreAccess } from "./actions";

type Params = Promise<{ id: string }>;
type Query = Promise<{ saved?: string; error?: string }>;

const messages: Record<string, string> = {
  validation: "حداقل یک فروشگاه، مجوز معتبر و یک فروشگاه پیش‌فرض انتخاب کنید.",
  reauth: "برای تغییر دسترسی‌ها، رمز فعلی را تأیید کنید.",
  store_permission_denied: "شما مدیر یکی از فروشگاه‌های درخواستی نیستید.",
  store_access_denied: "دسترسی فروشگاه یا نشست شما تغییر کرده است.",
  invalid_store_grants: "فهرست فروشگاه‌های انتخابی معتبر نیست.",
  invalid_store_default: "فروشگاه پیش‌فرض باید در فهرست مجاز باشد.",
  last_store_manager: "آخرین مدیر فروشگاه را نمی‌توان حذف یا تنزل داد.",
  staff_not_found: "حساب کاربر یافت نشد.",
};

/** Configure user Store membership, never the operator's own escalated grants. */
export default async function StaffStoresPage({
  params, searchParams,
}: { params: Params; searchParams: Query }) {
  const operator = await currentStaff();
  if (operator.role !== "superadmin") notFound();
  const { id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const memberId = Number(id);
  const data = await adminFetch<StaffStorePermissions>(
    `/staff/${memberId}/store-access`,
  );
  const query = await searchParams;
  return <div className="space-y-6">
    <Button asChild variant="outline" size="sm">
      <Link href="/staff">بازگشت به کارکنان</Link>
    </Button>
    <PageHeading title={`دسترسی فروشگاه‌های کاربر #${memberId}`}
      description="فروشگاه‌های مجاز، سطح دسترسی و فروشگاه پیش‌فرض این کاربر را تعیین کنید." />
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      دسترسی فروشگاه‌ها ذخیره شد؛ حذف دسترسی از درخواست بعدی اعمال می‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {messages[query.error] ?? "ذخیره انجام نشد؛ نشست و مجوزها را بررسی کنید."}
    </p> : null}
    {memberId === operator.id ? <p role="status" className="rounded-lg border p-4 text-sm">
      برای جلوگیری از افزایش مجوز یا حذف ناخواستهٔ آخرین مدیر، تغییر عضویت خودتان
      از این صفحه مجاز نیست. مدیر دیگری باید مجوزهای شما را تغییر دهد.
    </p> : <Card>
      <CardHeader><CardTitle>فروشگاه‌های قابل مدیریت</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-7 text-muted-foreground">
          فقط فروشگاه‌هایی که شما مجوز مدیریت آنها را دارید و در محیطتان فعال
          هستند نمایش داده می‌شوند. تغییر نقش سراسری کاربر جداگانه انجام می‌شود؛
          دسترسی مؤثر، اشتراک مجوز سراسری و سطح فروشگاه است.
        </p>
        {!data.stores.length ? <p className="rounded-lg border p-3 text-sm">
          فروشگاهی برای مدیریت دسترسی در اختیار شما نیست.
        </p> : null}
        <PasswordActionForm action={saveStaffStoreAccess} className="space-y-5">
          <input type="hidden" name="staff_id" value={memberId} />
          <StaffStoreTable data={data} />
          <div className="grid gap-3 sm:grid-cols-2">
          </div>
          <Button type="submit" disabled={!data.stores.length}>ذخیره دسترسی فروشگاه‌ها</Button>
        </PasswordActionForm>
      </CardContent>
    </Card>}
  </div>;
}
