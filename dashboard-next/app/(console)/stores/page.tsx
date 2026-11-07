import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreContextSnapshot } from "@/lib/store-context";
import type { StoreCommercePolicy } from "@/lib/store-commerce";
import type { CustomerMenuPolicy, CheckoutPolicy } from "@/lib/customer-experience";
import { CustomerExperiencePolicyPanel } from "@/components/blocks/customer-experience-policy-panel";
import { saveStoreCommercePolicy } from "./commerce-actions";

type Query = Promise<{
  saved?: string; error?: string; ux_saved?: string; ux_error?: string;
}>;

/** Configured Store boundaries, with explicit and conservative sharing. */
export default async function StoresPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const context = await adminFetch<StoreContextSnapshot>("/store-context");
  const stores = context.stores.filter(store => context.active_store_ids.includes(store.id));
  const policies = await Promise.all(stores.map(item =>
    adminFetch<StoreCommercePolicy>(`/stores/${item.id}/commerce`),
  ));
  const menuPolicies = await Promise.all(stores.map(item =>
    adminFetch<CustomerMenuPolicy>(`/stores/${item.id}/customer-menu`),
  ));
  const checkoutPolicies = await Promise.all(stores.map(item =>
    adminFetch<CheckoutPolicy>(`/stores/${item.id}/checkout-policy`),
  ));
  const note = query.error === "legacy_credit_requires_reconciliation"
    ? "برای فعال‌سازی اعتبار مشترک، ابتدا ماندهٔ تمام حساب‌های قبلی باید با اسناد مالی و رضایت مشتری تطبیق داده شود."
    : query.error === "reauth" ? "تأیید مجدد رمز و MFA لازم است."
    : query.error ? "ثبت سیاست انجام نشد؛ نسخه یا مجوزها را بررسی کنید."
    : "";

  return <div className="space-y-6">
    <PageHeading title="فروشگاه‌ها" />
    <div className="flex flex-wrap gap-3">
      <Button asChild variant="outline"><Link href="/bots">مدیریت ربات‌ها</Link></Button>
      <Button asChild variant="outline"><Link href="/payment-accounts">حساب‌های پرداخت</Link></Button>
      <Button asChild variant="outline"><Link href="/store-customers">مشتریان فروشگاه</Link></Button>
    </div>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      سیاست فروشگاه ذخیره شد؛ هیچ اعتبار یا سفارش قدیمی منتقل نشده است.
    </p> : null}
    {note ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {note}
    </p> : null}
    {query.ux_saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تنظیمات منو و خرید فروشگاه ذخیره شد.
    </p> : null}
    {query.ux_error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      تنظیمات خرید ذخیره نشد؛ فروشگاه جاری، مجوزها، شرایط فروش و MFA را بررسی کنید.
    </p> : null}
    <p className="text-sm leading-7 text-muted-foreground">
      اشتراک سبد خرید تنها برای هویت‌های متصل و تأییدشده عمل می‌کند. در حالت اشتراک،
      سبدهای قبلی جداگانه حفظ می‌شوند و هیچ ادغامی خودکار نیست. اعتبار مشترک هم
      تا انتقال حسابرسی‌شدهٔ مانده‌های موجود، فعال نخواهد شد.
    </p>
    {!stores.length ? <p className="rounded-lg border p-4 text-sm">
      هنوز فروشگاهی ثبت نشده است. <Link href="/bots" className="underline">فروشگاه ایجاد کنید</Link>.
    </p> : null}
    <div className="grid gap-4 xl:grid-cols-2">
      {stores.map((store, index) => {
        const policy = policies[index];
        return <Card key={store.id}>
          <CardHeader><CardTitle>{store.name}</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs text-muted-foreground">
              <bdi>{store.slug}</bdi> · {({ active: "فعال", paused: "متوقف", disabled: "غیرفعال", draft: "پیش‌نویس", archived: "بایگانی‌شده" } as Record<string, string>)[store.state] ?? store.state} · نسخهٔ سیاست {policy.version}
            </p>
            <form action={saveStoreCommercePolicy} className="space-y-4">
              <input type="hidden" name="store_id" value={store.id} />
              <input type="hidden" name="expected_version" value={policy.version} />
              <label className="block space-y-2 text-sm">مالکیت سبد خرید
                <select name="cart_scope" defaultValue={policy.cart_scope}
                  className="block h-10 w-full rounded-md border bg-background px-3">
                  <option value="bot">هر ربات مستقل</option>
                  <option value="customer">مشتری تأییدشده در فروشگاه مشترک</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">مالکیت اعتبار داخلی
                <select name="credit_scope" defaultValue={policy.credit_scope}
                  className="block h-10 w-full rounded-md border bg-background px-3">
                  <option value="identity">اعتبار مستقل هر هویت پیام‌رسان</option>
                  <option value="customer">اعتبار مشترک مشتری پس از تطبیق موجودی</option>
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
              <Button type="submit" variant="outline">ذخیره تنظیمات اشتراک</Button>
            </form>
          </CardContent>
        </Card>;
      })}
    </div>
    <section className="space-y-4">
      <h2 className="text-lg font-semibold">منو و خرید هر فروشگاه</h2>
      {stores.map((store, index) =>
        <div key={store.id} className="space-y-3 rounded-xl border p-4">
          <h3 className="font-semibold">{store.name}</h3>
          <CustomerExperiencePolicyPanel
            scope="store" id={store.id}
            menu={menuPolicies[index]} checkout={checkoutPolicies[index]}
          />
        </div>)}
    </section>
  </div>;
}
