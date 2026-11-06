import Link from "next/link";
import { notFound } from "next/navigation";
import { saveChannelFeatures, savePaymentRails, saveReferralPolicy } from "@/app/(console)/settings/actions";
import { ShopSettingsForm } from "@/components/blocks/shop-settings-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { ShopSettings } from "@/lib/types";

type Params = Promise<{ saved?: string; error?: string }>;
type ChannelFeature = { platform: "telegram" | "bale"; cart_enabled: boolean; store_credit_enabled: boolean; store_credit_label: string };
type PaymentRail = { platform: "telegram" | "bale"; rail_type: string; display_name: string; enabled: boolean; configured: boolean; runtime_ready: boolean; effective_enabled: boolean };

/** Admin-controlled brand, welcome, help and FAQ, shared by both bots. */
export default async function SettingsPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [settings, policy, channels, paymentRails, params] = await Promise.all([
    adminFetch<ShopSettings>("/settings"),
    adminFetch<{is_enabled: boolean; percent: number; min_order_irr: string; max_bonus_irr: string}>("/referral-policy"),
    adminFetch<{ items: ChannelFeature[] }>("/channel-features"),
    adminFetch<{ items: PaymentRail[] }>("/payment-rails"),
    searchParams,
  ]);
  return (
    <div>
      <PageHeading title="تنظیمات فروشگاه" />
      {params.saved ? <p role="status" className="mb-4 rounded-lg bg-accent p-3 text-sm text-accent-foreground">تنظیمات ذخیره شد.</p> : null}
      {params.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ذخیره تنظیمات انجام نشد؛ ابتدا MFA و تأیید مجدد هویت، سپس دسترسی و داده‌ها را بررسی کنید.</p> : null}
      <Card className="max-w-4xl">
        <CardHeader><CardTitle>متن‌های تلگرام و بله</CardTitle></CardHeader>
        <CardContent>
          <ShopSettingsForm initial={settings} />
        </CardContent>
      </Card>
      <Card className="mt-6 max-w-4xl">
        <CardHeader>
          <CardTitle>قابلیت‌های تلگرام و بله</CardTitle>
          <CardDescription>سبد خرید و اعتبار داخلی برای هر پیام‌رسان مستقل است. غیرفعال‌سازی سوابق خرید، موجودی یا دفتر مالی را پاک نمی‌کند.</CardDescription>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-xs leading-7 text-muted-foreground">برای تغییر این گزینه‌ها، در <Link href="/account" className="font-medium underline">حساب من</Link> هویت خود را مجدداً تأیید کنید. «اعتبار داخلی» با Bale Wallet و Telegram Stars تفاوت دارد.</p>
          <form action={saveChannelFeatures} className="space-y-5">
            {channels.items.map((channel) => <fieldset key={channel.platform} className="space-y-3 rounded-lg border p-4">
              <legend className="px-2 font-semibold">{channel.platform === "telegram" ? "تلگرام" : "بله"}</legend>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name={`${channel.platform}_cart_enabled`} defaultChecked={channel.cart_enabled} className="size-4 accent-primary" />
                سبد خرید و ثبت سفارش جدید فعال باشد
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" name={`${channel.platform}_store_credit_enabled`} defaultChecked={channel.store_credit_enabled} className="size-4 accent-primary" />
                اعتبار داخلی فروشگاه و پرداخت با اعتبار فعال باشد
              </label>
              <label className="block space-y-2 text-sm">عنوان اعتبار داخلی در این پیام‌رسان
                <Input name={`${channel.platform}_store_credit_label`} defaultValue={channel.store_credit_label} maxLength={80} required />
              </label>
            </fieldset>)}
            <Button type="submit">ذخیره قابلیت‌های پیام‌رسان‌ها</Button>
          </form>
        </CardContent>
      </Card>
      <Card className="mt-6 max-w-4xl">
        <CardHeader>
          <CardTitle>روش‌های پرداخت</CardTitle>

        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs leading-7 text-muted-foreground">
            برای استفاده از هر روش پرداخت، تنظیمات اتصال آن نیز باید تکمیل شده باشد.
          </p>
          <form action={savePaymentRails} className="space-y-5">
            {(["telegram", "bale"] as const).map((platform) => <fieldset key={platform} className="space-y-3 rounded-xl border p-4">
              <legend className="px-2 font-semibold">{platform === "telegram" ? "تلگرام" : "بله"}</legend>
              {paymentRails.items.filter(item => item.platform === platform).map(item => <div key={item.rail_type} className="grid gap-2 rounded-lg border p-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
                <label className="space-y-1 text-sm">نام روش پرداخت ({item.rail_type})
                  <Input name={`${platform}_${item.rail_type}_name`} defaultValue={item.display_name} maxLength={80} required />
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name={`${platform}_${item.rail_type}_enabled`} defaultChecked={item.enabled} className="size-4 accent-primary" />
                  فعال
                </label>
                <p className="text-xs text-muted-foreground md:col-span-2">
                  {item.runtime_ready ? (item.effective_enabled ? "قابل استفاده با پیکربندی فعلی" : "در تنظیمات غیرفعال است") :
                    "اتصال این روش پرداخت آماده نیست؛ تنظیمات آن در سرور باید تکمیل شود."}
                </p>
              </div>)}
            </fieldset>)}
            <Button type="submit">ذخیره روش‌های پرداخت</Button>
          </form>
        </CardContent>
      </Card>
      <Card className="mt-6 max-w-4xl">
        <CardHeader><CardTitle>پاداش معرفی مشتری</CardTitle><CardDescription>پاداش خرید اول از اعتبار داخلی فروشگاه تأمین می‌شود؛ هیچ موجودی بله یا رمز ارز تغییر نمی‌کند.</CardDescription></CardHeader>
        <CardContent>
          <form action={saveReferralPolicy} className="grid gap-4 md:grid-cols-2">
            <label className="flex items-center gap-2 text-sm md:col-span-2">
              <input type="checkbox" name="is_enabled" defaultChecked={policy.is_enabled} className="size-4 accent-primary" />
              فعال‌بودن پاداش معرفی
            </label>
            <label className="space-y-2 text-sm">درصد پاداش (۰ تا ۳۰)
              <Input type="number" name="percent" min={0} max={30} defaultValue={policy.percent} required />
            </label>
            <label className="space-y-2 text-sm">حداقل مبلغ خرید به ریال
              <Input type="number" name="min_order_irr" min={0} max={100000000000} defaultValue={policy.min_order_irr} required />
            </label>
            <label className="space-y-2 text-sm">سقف پاداش به ریال
              <Input type="number" name="max_bonus_irr" min={0} max={100000000000} defaultValue={policy.max_bonus_irr} required />
            </label>
            <div className="md:col-span-2"><Button type="submit">ذخیره پاداش معرفی</Button></div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
