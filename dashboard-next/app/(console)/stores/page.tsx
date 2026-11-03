import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreRecord } from "@/lib/bot-registry";
import type { StoreCommercePolicy } from "@/lib/store-commerce";
import { saveStoreCommercePolicy } from "./commerce-actions";

type Query = Promise<{ saved?: string; error?: string }>;
type StoreList = { items: StoreRecord[]; default_store_id: string };

/** Configured Store boundaries, with explicit and conservative sharing. */
export default async function StoresPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const stores = await adminFetch<StoreList>("/stores");
  const policies = await Promise.all(stores.items.map(item =>
    adminFetch<StoreCommercePolicy>(`/stores/${item.id}/commerce`),
  ));
  const note = query.error === "legacy_credit_requires_reconciliation"
    ? "برای فعال‌سازی اعتبار مشترک، ابتدا ماندهٔ تمام حساب‌های قبلی باید با اسناد مالی و رضایت مشتری تطبیق داده شود."
    : query.error === "reauth" ? "تأیید مجدد رمز و MFA لازم است."
    : query.error ? "ثبت سیاست انجام نشد؛ نسخه یا مجوزها را بررسی کنید."
    : "";

  return <div className="space-y-6">
    <PageHeading title="فروشگاه‌ها و سیاست اشتراک"
      description="کالا و مشتری متعلق به Store هستند؛ اشتراک سبد و اعتبار فقط با انتخاب صریح انجام می‌شود." />
    <div className="flex flex-wrap gap-3">
      <Button asChild variant="outline"><Link href="/bots">مدیریت بات‌ها</Link></Button>
      <Button asChild variant="outline"><Link href="/payment-accounts">حساب‌های پرداخت</Link></Button>
      <Button asChild variant="outline"><Link href="/store-customers">مشتریان فروشگاه</Link></Button>
    </div>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      سیاست فروشگاه ذخیره شد؛ هیچ اعتبار یا سفارش قدیمی منتقل نشده است.
    </p> : null}
    {note ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {note}
    </p> : null}
    <p className="text-sm leading-7 text-muted-foreground">
      اشتراک Cart تنها برای هویت‌های متصل و تأییدشده عمل می‌کند. در حالت اشتراک،
      سبدهای قبلی جداگانه حفظ می‌شوند و هیچ ادغامی خودکار نیست. اعتبار مشترک هم
      تا انتقال حسابرسی‌شدهٔ مانده‌های موجود، فعال نخواهد شد.
    </p>
    <div className="grid gap-4 xl:grid-cols-2">
      {stores.items.map((store, index) => {
        const policy = policies[index];
        return <Card key={store.id}>
          <CardHeader><CardTitle>{store.name}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs text-muted-foreground">
              {store.slug} · {store.state} · نسخهٔ سیاست {policy.version}
            </p>
            <form action={saveStoreCommercePolicy} className="space-y-4">
              <input type="hidden" name="store_id" value={store.id} />
              <input type="hidden" name="expected_version" value={policy.version} />
              <label className="block space-y-2 text-sm">مالکیت سبد خرید
                <select name="cart_scope" defaultValue={policy.cart_scope}
                  className="block h-10 w-full rounded-md border bg-background px-3">
                  <option value="bot">هر بات مستقل</option>
                  <option value="customer">مشتری تأییدشده در Store مشترک</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">مالکیت اعتبار داخلی
                <select name="credit_scope" defaultValue={policy.credit_scope}
                  className="block h-10 w-full rounded-md border bg-background px-3">
                  <option value="identity">اعتبار مستقل هر Identity</option>
                  <option value="customer">اعتبار مشترک مشتری پس از تطبیق موجودی</option>
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
              <Button type="submit" variant="outline">ذخیرهٔ سیاست Store</Button>
            </form>
          </CardContent>
        </Card>;
      })}
    </div>
  </div>;
}
