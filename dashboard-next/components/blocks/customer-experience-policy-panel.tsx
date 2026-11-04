import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  CheckoutPolicy, CustomerMenuPolicy,
} from "@/lib/customer-experience";
import {
  saveCustomerMenu, saveCheckoutPolicy,
} from "@/app/(console)/customer-experience/actions";

interface Props {
  scope: "store" | "bot";
  id: string;
  menu: CustomerMenuPolicy;
  checkout: CheckoutPolicy;
}

function Proof() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">رمز فعلی مدیر
      <Input name="current_password" type="password"
        autoComplete="current-password" required />
    </label>
    <label className="block space-y-2 text-sm">کد شش‌رقمی MFA
      <Input name="second_factor" inputMode="numeric"
        pattern="[0-9]{6}" maxLength={6}
        autoComplete="one-time-code" required />
    </label>
  </div>;
}

/** Per-Store defaults and Bot overrides for the SAME six customer menus. */
export function CustomerExperiencePolicyPanel({
  scope, id, menu, checkout,
}: Props) {
  const isBot = scope === "bot";
  return <div className="grid gap-4 xl:grid-cols-2">
    <Card>
      <CardHeader><CardTitle>
        {isBot ? "منوی این Bot" : "منوی پیش‌فرض Store"}
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7 text-muted-foreground">
          ترتیب دکمه‌ها، نمایش یا پنهان‌کردن آنها قابل تنظیم است. هر دکمه
          فقط هنگام مجازبودن قابلیت در Backend فعال خواهد بود؛ منو نمی‌تواند
          ACL محصولات یا درگاه پرداخت را دور بزند.
        </p>
        {menu.inherited ? <p className="text-xs text-muted-foreground">
          این Bot اکنون منوی پیش‌فرض Store را به ارث می‌برد.
        </p> : null}
        <form action={saveCustomerMenu} className="space-y-4">
          <input type="hidden" name="scope" value={scope} />
          <input type="hidden" name="target_id" value={id} />
          <input type="hidden" name="expected_version" value={menu.version} />
          <div className="space-y-2">
            {menu.available_actions.map((action, i) =>
              <div key={action.key} className="flex items-center gap-3 rounded-lg border p-3">
                <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                  <input type="checkbox" name="menu_action"
                    value={action.key}
                    defaultChecked={menu.actions.includes(action.key)}
                    disabled={action.key === "shop"} />
                  {action.key === "shop" ? <input type="hidden" name="menu_action" value="shop" /> : null}
                  <span className="truncate">{action.label}</span>
                </label>
                <label className="flex items-center gap-2 text-xs">
                  ترتیب
                  <select name={`order:${action.key}`}
                    defaultValue={menu.actions.indexOf(action.key) >= 0
                      ? menu.actions.indexOf(action.key) + 1 : i + 1}
                    className="h-9 rounded-md border bg-background px-2">
                    {[1, 2, 3, 4, 5, 6].map(value =>
                      <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
              </div>)}
          </div>
          <Proof />
          <Button type="submit" variant="outline">ذخیرهٔ منوی مشتری</Button>
        </form>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>
        {isBot ? "Checkout این Bot" : "Checkout و شرایط فروش Store"}
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7 text-muted-foreground">
          Manual Approval به‌صورت پیش‌فرض ایمن است؛ Instant فقط با شرایط
          فروش ثبت‌شده و روش پرداخت مجاز فعال می‌شود. کالاهای دیجیتال
          Telegram همچنان فقط با Telegram Stars قابل خریدند.
        </p>
        <form action={saveCheckoutPolicy} className="space-y-4">
          <input type="hidden" name="scope" value={scope} />
          <input type="hidden" name="target_id" value={id} />
          <input type="hidden" name="expected_version" value={checkout.version} />
          <label className="block space-y-2 text-sm">سیاست تأیید سفارش
            <select name="mode" required defaultValue={
              isBot ? checkout.mode_override ?? "inherit" : checkout.mode
            } className="block h-10 w-full rounded-md border bg-background px-3">
              {isBot ? <option value="inherit">ارث‌بری از Store</option> : null}
              <option value="manual">Manual Approval — تأیید فروشنده</option>
              <option value="instant">Instant Checkout — آمادهٔ پرداخت</option>
            </select>
          </label>
          {!isBot ? <>
            <label className="block space-y-2 text-sm">نسخهٔ شرایط فروش
              <Input name="terms_version" defaultValue={checkout.terms_version}
                maxLength={32} required placeholder="v1" />
            </label>
            <label className="block space-y-2 text-sm">
              متن کامل شرایط خرید و بازپرداخت
              <Textarea name="terms_text" rows={7}
                maxLength={6000} defaultValue={checkout.terms_text}
                placeholder="شرایط پرداخت، تحویل، بازگشت وجه و پشتیبانی فروشگاه ..." />
            </label>
            {!checkout.terms_ready ? <p className="text-xs text-destructive">
              شرایط فروش ثبت نشده است؛ Checkout تا تکمیل متن غیرفعال است.
            </p> : null}
          </> : <p className="text-xs text-muted-foreground">
            شرایط خرید متعلق به Store است و Bot اجازهٔ تغییر مستقل آنها را ندارد.
          </p>}
          <Proof />
          <Button type="submit" variant="outline">ذخیرهٔ سیاست Checkout</Button>
        </form>
      </CardContent>
    </Card>
  </div>;
}
