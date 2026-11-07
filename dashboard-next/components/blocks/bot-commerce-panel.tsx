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
      <Input name="second_factor" dir="ltr" inputMode="numeric" pattern="[0-9]{6}"
        maxLength={6} autoComplete="one-time-code" required />
    </label>
  </div>;
}

/** Every new registered bot requires explicit merchant feature permission. */
export function BotCommercePanel({ bot, policy, paymentAccounts }: Props) {
  const isRegistry = bot.runtime_owner === "registry";
  return <Card>
    <CardHeader><CardTitle>مجوزهای فروش و حساب‌های پرداخت این ربات</CardTitle></CardHeader>
    <CardContent className="space-y-6 text-sm">
      <p className="leading-7 text-muted-foreground">
        سبد خرید، اعتبار داخلی و حساب‌های پرداخت مجاز این ربات را تنظیم کنید.
      </p>
      <form action={saveBotCommercePolicy} className="space-y-4 rounded-xl border p-4">
        <p className="font-semibold">سبد خرید و اعتبار داخلی — نسخه {policy.version}</p>
        <input type="hidden" name="bot_id" value={bot.id} />
        <input type="hidden" name="expected_version" value={policy.version} />
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block space-y-2">سبد خرید
            <select name="cart_enabled"
              defaultValue={policy.cart_enabled === null ? "inherit" : String(policy.cart_enabled)}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="inherit">{isRegistry ? "بدون تنظیم — غیرفعال" : "استفاده از تنظیمات اتصال قدیمی"}</option>
              <option value="true">فعال</option>
              <option value="false">غیرفعال</option>
            </select>
          </label>
          <label className="block space-y-2">اعتبار داخلی
            <select name="credit_enabled"
              defaultValue={policy.credit_enabled === null ? "inherit" : String(policy.credit_enabled)}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="inherit">{isRegistry ? "بدون تنظیم — غیرفعال" : "استفاده از تنظیمات اتصال قدیمی"}</option>
              <option value="true">فعال</option>
              <option value="false">غیرفعال</option>
            </select>
          </label>
          <label className="block space-y-2 sm:col-span-2">عنوان اعتبار داخلی در ربات
            <Input name="credit_label" maxLength={80}
              defaultValue={policy.credit_label ?? ""} placeholder="اعتبار فروشگاه" />
          </label>
        </div>
        <MfaFields />
        <Button type="submit" variant="outline">ذخیرهٔ مجوزهای این ربات</Button>
      </form>

      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">حساب‌های پرداخت مجاز</p>
          <Button asChild variant="outline" size="sm">
            <Link href="/payment-accounts">افزودن حساب پرداخت</Link>
          </Button>
        </div>
        {!isRegistry ? <p className="text-muted-foreground">
          روش‌های پرداخت ربات قدیمی در تنظیمات اتصال مدیریت می‌شوند. Token فعال آن به‌صورت خودکار منتقل نمی‌شود.
        </p> : null}
        {isRegistry && !paymentAccounts.items.length ? <p className="rounded-lg border p-3 text-muted-foreground">
          حساب پرداختی برای این فروشگاه و پیام‌رسان ثبت نشده است. ابتدا حساب پرداخت اضافه کنید.
        </p> : null}
        {isRegistry && paymentAccounts.items.map(account => <form
          key={account.id} action={setBotPaymentAccess}
          className="space-y-3 rounded-lg border p-4">
          <input type="hidden" name="bot_id" value={bot.id} />
          <input type="hidden" name="account_id" value={account.id} />
          <div className="flex flex-wrap justify-between gap-2">
            <p className="font-medium">{account.name} · {account.rail_type}</p>
            <span className="text-xs text-muted-foreground">{({ draft: "پیش‌نویس", active: "فعال", disabled: "غیرفعال" } as const)[account.state]} · <bdi>{account.currency}</bdi></span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-2">دسترسی ربات به این حساب
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
          <Button type="submit" variant="outline">ذخیره دسترسی حساب پرداخت</Button>
          <p className="text-xs text-muted-foreground">
            برای فعال‌کردن دسترسی، حساب پرداخت باید فعال باشد. سوابق مالی تغییر نمی‌کنند.
          </p>
        </form>)}
      </div>
    </CardContent>
  </Card>;
}
