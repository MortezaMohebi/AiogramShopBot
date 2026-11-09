import { CustomerMenuOrder } from "@/components/blocks/customer-menu-order";
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
      <Input name="second_factor" dir="ltr" inputMode="numeric"
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
        {isBot ? "منوی این ربات" : "منوی پیش‌فرض فروشگاه"}
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7 text-muted-foreground">
          نمایش و ترتیب دکمه‌ها را تنظیم کنید. نمایش دکمه، دسترسی به محصول یا روش پرداخت را تغییر نمی‌دهد.
        </p>
        {menu.inherited ? <p className="text-xs text-muted-foreground">
          این ربات از منوی پیش‌فرض فروشگاه استفاده می‌کند.
        </p> : null}
        <form action={saveCustomerMenu} className="space-y-4">
          <input type="hidden" name="scope" value={scope} />
          <input type="hidden" name="target_id" value={id} />
          <input type="hidden" name="expected_version" value={menu.version} />
          <CustomerMenuOrder key={`${id}:${menu.version}`} menu={menu} />
          <Proof />
          <Button type="submit" variant="outline">ذخیرهٔ منوی مشتری</Button>
        </form>
      </CardContent>
    </Card>

    <Card>
      <CardHeader><CardTitle>
        {isBot ? "خرید در این ربات" : "خرید و شرایط فروشگاه"}
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7 text-muted-foreground">
          پرداخت فوری به شرایط فروش ثبت‌شده و روش پرداخت مجاز نیاز دارد. کالاهای دیجیتال تلگرام فقط با Telegram Stars قابل خریدند.
        </p>
        <form action={saveCheckoutPolicy} className="space-y-4">
          <input type="hidden" name="scope" value={scope} />
          <input type="hidden" name="target_id" value={id} />
          <input type="hidden" name="expected_version" value={checkout.version} />
          <label className="block space-y-2 text-sm">سیاست تأیید سفارش
            <select name="mode" required defaultValue={
              isBot ? checkout.mode_override ?? "inherit" : checkout.mode
            } className="block h-10 w-full rounded-md border bg-background px-3">
              {isBot ? <option value="inherit">استفاده از تنظیمات فروشگاه</option> : null}
              <option value="manual">نیازمند تأیید فروشنده</option>
              <option value="instant">پرداخت فوری</option>
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
              شرایط فروش ثبت نشده است؛ خرید تا تکمیل متن غیرفعال است.
            </p> : null}
          </> : <p className="text-xs text-muted-foreground">
            شرایط خرید در تنظیمات فروشگاه ویرایش می‌شود و برای این ربات نیز اعمال می‌شود.
          </p>}
          <Proof />
          <Button type="submit" variant="outline">ذخیره تنظیمات خرید</Button>
        </form>
      </CardContent>
    </Card>
  </div>;
}
