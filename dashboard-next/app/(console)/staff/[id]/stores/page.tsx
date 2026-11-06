import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StaffStorePermissions } from "@/lib/store-context";
import { saveStaffStoreAccess } from "./actions";

type Params = Promise<{ id: string }>;
type Query = Promise<{ saved?: string; error?: string }>;

const messages: Record<string, string> = {
  validation: "حداقل یک فروشگاه، مجوز معتبر و یک فروشگاه پیش‌فرض انتخاب کنید.",
  reauth: "برای تغییر دسترسی‌ها، رمز و MFA فعلی را دوباره تأیید کنید.",
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
        <form action={saveStaffStoreAccess} className="space-y-5">
          <input type="hidden" name="staff_id" value={memberId} />
          <div className="space-y-3">
            {data.stores.map(store => <div key={store.id}
              className="grid gap-3 rounded-xl border p-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <label className="flex items-center gap-3 text-sm">
                <input name="store_ids" type="checkbox" value={store.id}
                  defaultChecked={store.granted} />
                <span className="min-w-0">
                  <span className="block font-semibold">{store.name}</span>
                  <span className="text-xs text-muted-foreground"><bdi>{store.slug}</bdi> · {({ active: "فعال", paused: "متوقف", disabled: "غیرفعال", draft: "پیش‌نویس", archived: "بایگانی‌شده" } as Record<string, string>)[store.state] ?? store.state}</span>
                </span>
              </label>
              <label className="block space-y-2 text-sm">سطح دسترسی
                <select name={`access:${store.id}`}
                  defaultValue={store.access_level ?? "viewer"}
                  className="block h-10 rounded-md border bg-background px-3">
                  <option value="viewer">مشاهده‌گر — فقط خواندن</option>
                  <option value="editor">ویرایشگر — ویرایش مطابق نقش</option>
                  <option value="manager">مدیر — مدیریت فروشگاه</option>
                </select>
              </label>
            </div>)}
          </div>
          <label className="block max-w-xl space-y-2 text-sm">
            فروشگاه پیش‌فرض کاربر پس از ورود
            <select name="default_store_id"
              defaultValue={data.default_store_id ?? data.stores.find(x => x.granted)?.id ?? ""}
              className="block h-10 w-full rounded-md border bg-background px-3">
              {data.stores.map(store =>
                <option key={store.id} value={store.id}>{store.name}</option>)}
            </select>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-2 text-sm">رمز فعلی مدیر
              <Input name="current_password" type="password" required
                autoComplete="current-password" />
            </label>
            <label className="block space-y-2 text-sm">کد MFA
              <Input name="second_factor" dir="ltr" inputMode="numeric" pattern="[0-9]{6}"
                maxLength={6} autoComplete="one-time-code" required />
            </label>
          </div>
          <Button type="submit" disabled={!data.stores.length}>ذخیره دسترسی فروشگاه‌ها</Button>
        </form>
      </CardContent>
    </Card>}
  </div>;
}
