import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreContextSnapshot } from "@/lib/store-context";
import type { UomList } from "@/lib/uoms";
import { createUomCategory, createUomUnit } from "./actions";

type Params = Promise<{ saved?: string; error?: string }>;
const MESSAGES: Record<string, string> = {
  validation: "کد واحد، نسبت تبدیل و سایر فیلدها را بررسی کنید.",
  invalid_uom: "تعریف واحد معتبر نیست.",
  uom_already_exists: "کد واحد یا دسته‌بندی قبلاً در این فروشگاه تعریف شده است.",
  uom_category_not_found: "دسته‌بندی واحد در فروشگاه فعلی موجود نیست.",
  store_switch_required: "ابتدا فروشگاه را انتخاب کنید.",
  store_permission_denied: "برای تعریف واحد به دسترسی مدیر فروشگاه نیاز دارید.",
  reauth: "برای این تغییر باید هویت مدیر دوباره تأیید شود.",
};

/** Manage Store-specific UoM categories, reference units and exact ratios. */
export default async function UomsPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [context, params] = await Promise.all([
    adminFetch<StoreContextSnapshot>("/store-context"),
    searchParams,
  ]);
  const storeId = context.current_store_id;
  const data = await adminFetch<UomList>(`/stores/${storeId}/uoms`);
  const store = context.stores.find((item) => item.id === storeId);
  const isManager = store?.access_level === "manager";

  return <div className="space-y-6">
    <PageHeading title="واحدهای اندازه‌گیری"
      description={`واحدهای فروشگاه: ${store?.name ?? "نامشخص"}`} />
    <div className="flex flex-wrap gap-2">
      <Button asChild size="sm" variant="outline"><Link href="/products">محصولات</Link></Button>
      <Button asChild size="sm" variant="outline"><Link href="/stores">فروشگاه‌ها</Link></Button>
    </div>
    {params.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      واحد اندازه‌گیری ثبت شد. موجودی یا سفارش‌های قبلی تبدیل نشده‌اند.
    </p> : null}
    {params.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {MESSAGES[params.error] ?? "ثبت انجام نشد."}
    </p> : null}
    <Card>
      <CardHeader><CardTitle>واحدهای تعریف‌شده</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs leading-7 text-muted-foreground">
          نسبت «صورت / مخرج» برحسب واحد مرجع همان دسته‌بندی است.
          مثال: ۱ دوجین برابر ۱۲ عدد؛ ۱ گرم برابر ۰٫۰۰۱ کیلوگرم.
          موجودی و سبد خرید فقط تعداد صحیح واحد فروش را می‌پذیرند.
        </p>
        {data.categories.map(category => <section key={category.id}
          className="space-y-2 rounded-lg border p-3">
          <h3 className="font-semibold">{category.name} ({category.code})</h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[570px] text-right text-sm">
              <thead><tr className="border-b">
                <th className="p-2">واحد</th>
                <th className="p-2">کد</th>
                <th className="p-2">نماد</th>
                <th className="p-2">نسبت تبدیل</th>
                <th className="p-2">نوع واحد</th>
              </tr></thead>
              <tbody>{data.items.filter((unit) => unit.category_id === category.id)
                .map(unit => <tr key={unit.id} className="border-b">
                  <td className="p-2">{unit.name}</td>
                  <td className="p-2" dir="ltr">{unit.code}</td>
                  <td className="p-2">{unit.symbol}</td>
                  <td className="p-2" dir="ltr">{unit.ratio_num}/{unit.ratio_den}</td>
                  <td className="p-2">{unit.reference ? "مرجع" : "تبدیلی"}</td>
                </tr>)}</tbody>
            </table>
          </div>
        </section>)}
        {!data.categories.length ? <p className="text-sm text-muted-foreground">
          هنوز واحدی تعریف نشده است. ابتدا دسته‌بندی و واحد مرجع را اضافه کنید.
        </p> : null}
      </CardContent>
    </Card>

    {isManager ? <div className="grid gap-5 xl:grid-cols-2">
      <Card>
        <CardHeader><CardTitle>تعریف دسته‌بندی و واحد مرجع</CardTitle></CardHeader>
        <CardContent><form action={createUomCategory} className="space-y-4">
          <input type="hidden" name="store_id" value={storeId} />
          <label className="block space-y-2 text-sm">کد دسته‌بندی
            <Input name="code" dir="ltr" pattern="[a-z][a-z0-9_-]{0,31}"
              placeholder="surface" required />
          </label>
          <label className="block space-y-2 text-sm">نام دسته‌بندی
            <Input name="name" required placeholder="سطح" maxLength={120} />
          </label>
          <label className="block space-y-2 text-sm">کد واحد مرجع
            <Input name="base_code" dir="ltr" pattern="[a-z][a-z0-9_-]{0,31}"
              required placeholder="m2" />
          </label>
          <label className="block space-y-2 text-sm">نام واحد مرجع
            <Input name="base_name" required placeholder="مترمربع" />
          </label>
          <label className="block space-y-2 text-sm">نماد
            <Input name="base_symbol" dir="ltr" required placeholder="m²" maxLength={24} />
          </label>
          <Button type="submit" variant="outline">ثبت دسته‌بندی</Button>
        </form></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>افزودن واحد تبدیلی</CardTitle></CardHeader>
        <CardContent><form action={createUomUnit} className="space-y-4">
          <input type="hidden" name="store_id" value={storeId} />
          <label className="block space-y-2 text-sm">دسته‌بندی
            <select name="category_id" required
              className="block h-10 w-full rounded-md border bg-background px-3">
              {data.categories.map(category => <option key={category.id} value={category.id}>
                {category.name}
              </option>)}
            </select>
          </label>
          <label className="block space-y-2 text-sm">کد واحد
            <Input name="code" dir="ltr" required pattern="[a-z][a-z0-9_-]{0,31}"
              placeholder="box6" />
          </label>
          <label className="block space-y-2 text-sm">نام واحد
            <Input name="name" required placeholder="بسته ۶ تایی" />
          </label>
          <label className="block space-y-2 text-sm">نماد
            <Input name="symbol" dir="ltr" required placeholder="pack" maxLength={24} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block space-y-2 text-sm">صورت نسبت
              <Input name="ratio_num" dir="ltr" type="number" min={1} max={1000000000}
                defaultValue={6} required />
            </label>
            <label className="block space-y-2 text-sm">مخرج نسبت
              <Input name="ratio_den" dir="ltr" type="number" min={1} max={1000000000}
                defaultValue={1} required />
            </label>
          </div>
          <label className="block space-y-2 text-sm">حداقل گام تعداد
            <Input name="rounding" dir="ltr" inputMode="decimal" defaultValue="1" required />
          </label>
          <Button type="submit" variant="outline" disabled={!data.categories.length}>افزودن واحد</Button>
        </form></CardContent>
      </Card>
    </div> : <p className="text-sm text-muted-foreground">
      برای مدیریت واحدهای اندازه‌گیری به دسترسی مدیر فروشگاه نیاز دارید.
    </p>}
  </div>;
}
