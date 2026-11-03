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
  validation: "حداقل یک Store، مجوز معتبر و یک Store پیش‌فرض انتخاب کنید.",
  reauth: "برای تغییر دسترسی‌ها، رمز و MFA فعلی را دوباره تأیید کنید.",
  store_permission_denied: "شما مدیر یکی از Storeهای درخواستی نیستید.",
  store_access_denied: "دسترسی Store یا نشست شما تغییر کرده است.",
  invalid_store_grants: "فهرست Storeهای انتخابی معتبر نیست.",
  invalid_store_default: "Store پیش‌فرض باید در فهرست مجاز باشد.",
  last_store_manager: "آخرین مدیر Store را نمی‌توان حذف یا تنزل داد.",
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
      description="Allowed Stores، سطح دسترسی هر Store و Default Store مانند الگوی Multi-Company اودو." />
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      مجوزهای Store ذخیره شدند؛ حذف مجوز از درخواست بعدی اعمال می‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {messages[query.error] ?? "ذخیره انجام نشد؛ نشست و مجوزها را بررسی کنید."}
    </p> : null}
    {memberId === operator.id ? <p role="status" className="rounded-lg border p-4 text-sm">
      برای جلوگیری از افزایش مجوز یا حذف ناخواستهٔ آخرین مدیر، تغییر عضویت خودتان
      از این صفحه مجاز نیست. مدیر دیگری باید مجوزهای شما را تغییر دهد.
    </p> : <Card>
      <CardHeader><CardTitle>Storeهای قابل مدیریت</CardTitle></CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-7 text-muted-foreground">
          فقط Storeهایی که شما مجوز Manager آنها را دارید و در محیطتان فعال
          هستند نمایش داده می‌شوند. تغییر نقش سراسری کاربر جداگانه انجام می‌شود؛
          دسترسی مؤثر، اشتراک مجوز سراسری و سطح Store است.
        </p>
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
                  <span className="text-xs text-muted-foreground">{store.slug} · {store.state}</span>
                </span>
              </label>
              <label className="block space-y-2 text-sm">سطح دسترسی
                <select name={`access:${store.id}`}
                  defaultValue={store.access_level ?? "viewer"}
                  className="block h-10 rounded-md border bg-background px-3">
                  <option value="viewer">Viewer — فقط خواندن</option>
                  <option value="editor">Editor — نوشتن مطابق نقش</option>
                  <option value="manager">Manager — مدیریت Store</option>
                </select>
              </label>
            </div>)}
          </div>
          <label className="block max-w-xl space-y-2 text-sm">
            Store پیش‌فرض کاربر پس از ورود
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
              <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
                maxLength={6} autoComplete="one-time-code" required />
            </label>
          </div>
          <Button type="submit">ذخیرهٔ مجوز Storeهای این کاربر</Button>
        </form>
      </CardContent>
    </Card>}
  </div>;
}
