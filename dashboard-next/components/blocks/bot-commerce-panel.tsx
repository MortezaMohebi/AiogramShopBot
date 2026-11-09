import { BotPaymentTable } from "@/components/blocks/bot-payment-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { BotRecord } from "@/lib/bot-registry";
import type { BotCommercePolicy, BotPaymentList } from "@/lib/store-commerce";
import {
  saveBotCommercePolicy,
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
              <option value="inherit">بدون تنظیم — غیرفعال</option>
              <option value="true">فعال</option>
              <option value="false">غیرفعال</option>
            </select>
          </label>
          <label className="block space-y-2">اعتبار داخلی
            <select name="credit_enabled"
              defaultValue={policy.credit_enabled === null ? "inherit" : String(policy.credit_enabled)}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="inherit">بدون تنظیم — غیرفعال</option>
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

      <BotPaymentTable botId={bot.id} accounts={paymentAccounts.items} proof={<MfaFields />} />
    </CardContent>
  </Card>;
}
