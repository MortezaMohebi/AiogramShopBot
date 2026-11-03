import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { BotRecord } from "@/lib/bot-registry";
import type { BotCommercePolicy, BotPaymentList } from "@/lib/store-commerce";
import {
  saveBotCommercePolicy, setBotPaymentAccess,
} from "@/app/(console)/bots/[id]/commerce-actions";

interface Props {
  bot: BotRecord;
  policy: BotCommercePolicy;
  paymentAccounts: BotPaymentList;
}

function MfaFields() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">رمز فعلی مدیر
      <Input type="password" name="current_password" required
        autoComplete="current-password" maxLength={256} />
    </label>
    <label className="block space-y-2 text-sm">کد MFA
      <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
        maxLength={6} autoComplete="one-time-code" required />
    </label>
  </div>;
}

/** Every new registered bot requires explicit merchant feature permission. */
export function BotCommercePanel({ bot, policy, paymentAccounts }: Props) {
  const isRegistry = bot.runtime_owner === "registry";
  return <Card>
    <CardHeader><CardTitle>مجوزهای فروش و حساب‌های پرداخت این بات</CardTitle></CardHeader>
    <CardContent className="space-y-6 text-sm">
      <p className="leading-7 text-muted-foreground">
        Store مالک Customer، Catalog، Stock و اعتبار داخلی است. بات تنها
        دسترسی مجاز به قابلیت‌های فروش و Providerهای پرداخت را دارد.
        هیچ Token و موجودی کیف پول خارجی از این صفحه خوانده نمی‌شود.
      </p>
      <form action={saveBotCommercePolicy} className="space-y-4 rounded-xl border p-4">
        <p className="font-semibold">Cart و Store Credit — نسخه {policy.version}</p>
        <input type="hidden" name="bot_id" value={bot.id} />
        <input type="hidden" name="expected_version" value={policy.version} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2">سبد خرید
            <select name="cart_enabled"
              defaultValue={policy.cart_enabled === null ? "inherit" : String(policy.cart_enabled)}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="inherit">{isRegistry ? "بدون تنظیم — غیرفعال" : "ارث‌بری Legacy"}</option>
              <option value="true">فعال</option>
              <option value="false">غیرفعال</option>
            </select>
          </label>
          <label className="block space-y-2">اعتبار داخلی
            <select name="credit_enabled"
              defaultValue={policy.credit_enabled === null ? "inherit" : String(policy.credit_enabled)}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="inherit">{isRegistry ? "بدون تنظیم — غیرفعال" : "ارث‌بری Legacy"}</option>
              <option value="true">فعال</option>
              <option value="false">غیرفعال</option>
            </select>
          </label>
          <label className="block space-y-2 sm:col-span-2">عنوان اعتبار داخلی در بات
            <Input name="credit_label" maxLength={80}
              defaultValue={policy.credit_label ?? ""} placeholder="اعتبار فروشگاه" />
          </label>
        </div>
        <MfaFields />
        <Button type="submit" variant="outline">ذخیرهٔ مجوزهای این بات</Button>
      </form>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">Payment Accounts مجاز</p>
          <Button asChild variant="outline" size="sm">
            <Link href="/payment-accounts">تعریف حساب در Store</Link>
          </Button>
        </div>
        {!isRegistry ? <p className="text-muted-foreground">
          Providerهای بات Legacy در بخش تنظیمات اتصال قدیمی مدیریت می‌شوند؛
          هیچ Token فعالی خودکار به مدل جدید منتقل نمی‌شود.
        </p> : null}
        {isRegistry && !paymentAccounts.items.length ? <p className="rounded-lg border p-3 text-muted-foreground">
          حسابی برای این Store و پیام‌رسان ثبت نشده است؛ پرداخت جدید غیرفعال می‌ماند.
        </p> : null}
        {isRegistry && paymentAccounts.items.map(account => <form
          key={account.id} action={setBotPaymentAccess}
          className="space-y-3 rounded-lg border p-4">
          <input type="hidden" name="bot_id" value={bot.id} />
          <input type="hidden" name="account_id" value={account.id} />
          <div className="flex flex-wrap justify-between gap-2">
            <p className="font-medium">{account.name} · {account.rail_type}</p>
            <span className="text-xs text-muted-foreground">{account.state} · {account.currency}</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-2">دسترسی بات به این حساب
              <select name="enabled" defaultValue={account.granted ? "true" : "false"}
                className="block h-10 w-full rounded-md border bg-background px-3">
                <option value="false">غیرفعال</option>
                <option value="true">مجاز</option>
              </select>
            </label>
            <label className="block space-y-2">اولویت
              <Input name="priority" type="number" min={1} max={1000}
                defaultValue={account.priority} required />
            </label>
          </div>
          <MfaFields />
          <Button type="submit" variant="outline">ذخیرهٔ مجوز Provider</Button>
          <p className="text-xs text-muted-foreground">
            برای فعال‌کردن، Account باید Active باشد؛ مبلغ و وضعیت مالی سابق تغییر نمی‌کند.
          </p>
        </form>)}
      </div>
    </CardContent>
  </Card>;
}
