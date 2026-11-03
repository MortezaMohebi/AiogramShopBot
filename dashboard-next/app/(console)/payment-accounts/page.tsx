import Link from "next/link";
import { notFound } from "next/navigation";
import { CreditCard, KeyRound } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreRecord } from "@/lib/bot-registry";
import type { PaymentAccountList, PaymentRail } from "@/lib/store-commerce";
import {
  createPaymentAccount, setPaymentAccountState,
} from "./actions";

type StoreList = { items: StoreRecord[]; default_store_id: string };
type Query = Promise<{ store_id?: string; saved?: string; error?: string }>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const PROVIDERS: {
  platform: "telegram" | "bale";
  rail: PaymentRail;
  label: string;
  requiresToken: boolean;
}[] = [
  { platform: "bale", rail: "bale_wallet", label: "Bale Wallet (IRR)", requiresToken: true },
  { platform: "telegram", rail: "telegram_fiat", label: "Telegram Fiat (IRR)", requiresToken: true },
  { platform: "telegram", rail: "telegram_stars", label: "Telegram Stars (XTR)", requiresToken: false },
];

function ProofFields() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">رمز فعلی مدیر
      <Input name="current_password" type="password" autoComplete="current-password"
        maxLength={256} required />
    </label>
    <label className="block space-y-2 text-sm">کد شش‌رقمی MFA
      <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
        maxLength={6} autoComplete="one-time-code" required />
    </label>
  </div>;
}

/** No Provider Token reaches a client once it has been staged securely. */
export default async function PaymentAccountsPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const stores = await adminFetch<StoreList>("/stores");
  const storeId = query.store_id && UUID.test(query.store_id)
    ? query.store_id : stores.default_store_id;
  const accounts = await adminFetch<PaymentAccountList>(
    `/stores/${storeId}/payment-accounts`,
  );

  return <div className="space-y-6">
    <PageHeading title="حساب‌های پرداخت فروشگاه"
      description="Provider Account مشترک در Store، اما مجوز استفاده از آن برای هر Bot جداگانه و پیش‌فرض غیرفعال است." />
    <div className="flex flex-wrap gap-3">
      <Button asChild variant="outline"><Link href="/stores">سیاست فروشگاه</Link></Button>
      <Button asChild variant="outline"><Link href="/bots">بات‌های مجاز</Link></Button>
    </div>
    <form method="get" className="flex flex-wrap items-end gap-3">
      <label className="block space-y-2 text-sm">فروشگاه
        <select name="store_id" defaultValue={storeId}
          className="block h-10 min-w-48 rounded-md border bg-background px-3">
          {stores.items.map(store =>
            <option value={store.id} key={store.id}>{store.name}</option>)}
        </select>
      </label>
      <Button type="submit" variant="outline">نمایش</Button>
    </form>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تغییر حساب ذخیره شد؛ هیچ پرداخت یا فعال‌سازی خودکار باتی انجام نمی‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {query.error === "reauth" ? "تأیید مجدد هویت و MFA لازم است." :
        "عملیات ثبت نشد؛ تطبیق Provider، Secret و نسخه را بررسی کنید."}
    </p> : null}
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <CreditCard className="size-5" /> Providerهای تعریف‌شده
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {!accounts.items.length ? <p className="text-sm text-muted-foreground">
          هنوز هیچ Provider Account ثبت نشده است.
        </p> : null}
        {accounts.items.map(account => <div key={account.id} className="space-y-3 rounded-xl border p-4">
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <div>
              <p className="font-semibold">{account.name}</p>
              <p className="text-xs text-muted-foreground">
                {account.platform} · {account.rail_type} · {account.currency} · نسخه {account.version}
              </p>
            </div>
            <span>{account.state}</span>
          </div>
          <form action={setPaymentAccountState}
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_auto] xl:items-end">
            <input type="hidden" name="account_id" value={account.id} />
            <input type="hidden" name="expected_version" value={account.version} />
            <label className="block space-y-2 text-sm">وضعیت هدف
              <select name="state" defaultValue={account.state === "draft" ? "disabled" : account.state}
                className="block h-10 w-full rounded-md border bg-background px-3">
                <option value="active">Active — آمادهٔ تخصیص</option>
                <option value="disabled">Disabled</option>
              </select>
            </label>
            <label className="block space-y-2 text-sm">رمز فعلی
              <Input name="current_password" type="password"
                autoComplete="current-password" required />
            </label>
            <label className="block space-y-2 text-sm">کد MFA
              <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
                maxLength={6} autoComplete="one-time-code" required />
            </label>
            <Button type="submit" variant="outline">تغییر وضعیت</Button>
          </form>
        </div>)}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <KeyRound className="size-5" /> ثبت Provider Account جدید
      </CardTitle></CardHeader>
      <CardContent className="space-y-6">
        <p className="text-sm leading-7 text-muted-foreground">
          تنها Providerهای پشتیبانی‌شده قابل انتخاب‌اند. Telegram Stars نیازی
          به Token فیات ندارد. برای Bale Wallet یا Telegram Fiat، Token فقط هنگام
          ثبت وارد شده و به‌شکل رمزنگاری‌شده در Backend نگهداری می‌شود.
        </p>
        {PROVIDERS.map(provider => <form key={provider.rail}
          action={createPaymentAccount} className="space-y-4 rounded-xl border p-4">
          <p className="font-semibold">{provider.label}</p>
          <input type="hidden" name="store_id" value={storeId} />
          <input type="hidden" name="platform" value={provider.platform} />
          <input type="hidden" name="rail_type" value={provider.rail} />
          <label className="block space-y-2 text-sm">نام حساب
            <Input name="name" maxLength={100} required placeholder={provider.label} />
          </label>
          {provider.requiresToken ? <label className="block space-y-2 text-sm">
            Provider Token — فقط یک بار وارد کنید
            <Input name="token" type="password" minLength={20}
              maxLength={512} autoComplete="new-password" required dir="ltr" />
          </label> : null}
          <ProofFields />
          <Button type="submit" variant="outline">ثبت امن به حالت Draft</Button>
        </form>)}
      </CardContent>
    </Card>
  </div>;
}
