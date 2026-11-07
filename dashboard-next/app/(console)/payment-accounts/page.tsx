import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { CreditCard, KeyRound } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreContextSnapshot } from "@/lib/store-context";
import type { PaymentAccountList, PaymentRail } from "@/lib/store-commerce";
import {
  createPaymentAccount, setPaymentAccountState,
} from "./actions";

type Query = Promise<{ store_id?: string; saved?: string; error?: string }>;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const PROVIDERS: {
  platform: "telegram" | "bale";
  rail: PaymentRail;
  label: string;
  requiresToken: boolean;
}[] = [
  { platform: "bale", rail: "bale_wallet", label: "کیف پول بله (ریال)", requiresToken: true },
  { platform: "telegram", rail: "telegram_fiat", label: "پرداخت ریالی کالای فیزیکی در تلگرام", requiresToken: true },
  { platform: "telegram", rail: "telegram_stars", label: "Telegram Stars (XTR)", requiresToken: false },
];

function ProofFields() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">رمز فعلی مدیر
      <Input name="current_password" type="password" autoComplete="current-password"
        maxLength={256} required />
    </label>
    <label className="block space-y-2 text-sm">کد شش‌رقمی احراز هویت دومرحله‌ای
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
  const context = await adminFetch<StoreContextSnapshot>("/store-context");
  const stores = context.stores.filter(store => context.active_store_ids.includes(store.id));
  // A Store switch can leave the previous GET selection in the address bar.
  // Clear it before requesting policy data outside this session's active set.
  if (query.store_id && (!UUID.test(query.store_id) || !stores.some(store => store.id === query.store_id))) {
    redirect("/payment-accounts");
  }
  const storeId = query.store_id || context.current_store_id;
  const accounts = await adminFetch<PaymentAccountList>(
    `/stores/${storeId}/payment-accounts`,
  );
  const telegramFiatEnabled = accounts.telegram_fiat_enabled === true;
  const availableProviders = PROVIDERS.filter(
    provider => provider.rail !== "telegram_fiat" || telegramFiatEnabled,
  );

  return <div className="space-y-6">
    <PageHeading title="حساب‌های پرداخت فروشگاه"
      description="دسترسی هر ربات به حساب پرداخت جداگانه تعیین می‌شود و ابتدا غیرفعال است." />
    <div className="flex flex-wrap gap-3">
      <Button asChild variant="outline"><Link href="/stores">سیاست فروشگاه</Link></Button>
      <Button asChild variant="outline"><Link href="/bots">بات‌های مجاز</Link></Button>
    </div>
    <form method="get" className="flex flex-wrap items-end gap-3">
      <label className="block space-y-2 text-sm">فروشگاه
        <select name="store_id" defaultValue={storeId}
          className="block h-10 min-w-48 rounded-md border bg-background px-3">
          {stores.map(store =>
            <option value={store.id} key={store.id}>{store.name}</option>)}
        </select>
      </label>
      <Button type="submit" variant="outline">نمایش</Button>
    </form>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تغییر حساب ذخیره شد؛ هیچ پرداخت یا فعال‌سازی خودکار باتی انجام نمی‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {query.error === "reauth" ? "رمز فعلی و کد احراز هویت دومرحله‌ای را وارد کنید." :
        query.error === "telegram_fiat_unavailable" ? "پرداخت ریالی تلگرام در این نصب آماده نیست." :
        "حساب پرداخت ذخیره نشد. ارائه‌دهنده، توکن و وضعیت فعلی حساب را بررسی کنید."}
    </p> : null}
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <CreditCard className="size-5" /> حساب‌های پرداخت
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {!accounts.items.length ? <p className="text-sm text-muted-foreground">
          هنوز حساب پرداختی ثبت نشده است. از فرم زیر حساب اضافه کنید.
        </p> : null}
        <div className="grid items-start gap-3 md:grid-cols-2">
        {accounts.items.map(account => <div key={account.id} className="min-w-0 space-y-3 rounded-xl border p-3">
          <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
            <div>
              <p dir="auto" className="break-words font-semibold">{account.name}</p>
              <p className="text-xs text-muted-foreground">
                {PROVIDERS.find(provider => provider.rail === account.rail_type)?.label ?? account.rail_type}
              </p>
              {account.rail_type === "telegram_fiat" && !telegramFiatEnabled ?
                <p className="text-xs text-muted-foreground">دریافت پرداخت ریالی در این نصب غیرفعال است.</p>
                : null}
            </div>
            <span>{account.state === "active" ? "فعال" : account.state === "draft" ? "پیش‌نویس" : "غیرفعال"}</span>
          </div>
          <details>
            <summary className="w-fit cursor-pointer rounded-md px-1 text-sm font-medium hover:underline focus-visible:outline-2 focus-visible:outline-ring">
              مدیریت حساب
            </summary>
            <form action={setPaymentAccountState} className="mt-3 space-y-3 border-t pt-3">
            <input type="hidden" name="account_id" value={account.id} />
            <input type="hidden" name="expected_version" value={account.version} />
            <label className="block space-y-2 text-sm">وضعیت هدف
              <select name="state" defaultValue={account.state === "draft" ? "disabled" : account.state}
                className="block h-10 w-full rounded-md border bg-background px-3">
                <option value="active">فعال — آمادهٔ تخصیص</option>
                <option value="disabled">غیرفعال</option>
              </select>
            </label>
            <label className="block space-y-2 text-sm">رمز فعلی
              <Input name="current_password" type="password"
                autoComplete="current-password" required />
            </label>
            <label className="block space-y-2 text-sm">کد احراز هویت دومرحله‌ای
              <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
                maxLength={6} autoComplete="one-time-code" required />
            </label>
            <Button type="submit" variant="outline">تغییر وضعیت</Button>
            </form>
          </details>
        </div>)}
        </div>
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <KeyRound className="size-5" /> افزودن حساب پرداخت
      </CardTitle></CardHeader>
      <CardContent className="space-y-6">
        <p className="text-sm leading-7 text-muted-foreground">
          پرداخت کالای دیجیتال در تلگرام با Telegram Stars انجام می‌شود و به توکن درگاه نیاز ندارد.
          برای کیف پول بله توکن ارائه‌دهنده لازم است.
        </p>
        <div className="grid items-start gap-3 md:grid-cols-2">
        {availableProviders.map(provider => <details key={provider.rail} className="rounded-xl border p-3">
          <summary className="cursor-pointer rounded-md px-1 text-sm font-medium hover:underline focus-visible:outline-2 focus-visible:outline-ring">
            {provider.label}
          </summary>
          <form action={createPaymentAccount} className="mt-3 space-y-4 border-t pt-3">
          {provider.rail === "telegram_fiat" ?
            <p className="text-sm text-muted-foreground">
              این روش برای کالای فیزیکی است. درگاه متصل از طریق BotFather باید پرداخت به ریال ایران را پشتیبانی کند.
            </p> : null}
          <input type="hidden" name="store_id" value={storeId} />
          <input type="hidden" name="platform" value={provider.platform} />
          <input type="hidden" name="rail_type" value={provider.rail} />
          <label className="block space-y-2 text-sm">نام حساب
            <Input name="name" maxLength={100} required placeholder={provider.label} />
          </label>
          {provider.requiresToken ? <label className="block space-y-2 text-sm">
            توکن ارائه‌دهنده (فقط هنگام ثبت)
            <Input name="token" type="password" minLength={20}
              maxLength={512} autoComplete="new-password" required dir="ltr" />
          </label> : null}
          <ProofFields />
          <Button type="submit" variant="outline">ایجاد حساب پیش‌نویس</Button>
          </form>
        </details>)}
        </div>
      </CardContent>
    </Card>
  </div>;
}
