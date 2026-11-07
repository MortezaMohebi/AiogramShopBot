import Link from "next/link";
import { notFound } from "next/navigation";
import { saveReferralPolicy } from "@/app/(console)/settings/actions";
import { ShopSettingsForm } from "@/components/blocks/shop-settings-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff, optionalStoreRead } from "@/lib/bridge";
import type { ShopSettings } from "@/lib/types";

type Params = Promise<{ saved?: string; error?: string }>;

/** Admin-controlled brand, welcome, help and FAQ, shared by both bots. */
export default async function SettingsPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [settings, policy, params] = await Promise.all([
    adminFetch<ShopSettings>("/settings"),
    optionalStoreRead<{is_enabled: boolean; percent: number; min_order_irr: string; max_bonus_irr: string}>("/referral-policy"),
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
      {policy ? <Card className="mt-6 max-w-4xl">
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
      </Card> : null}
      {<Card className="mt-6 max-w-4xl">
        <CardHeader><CardTitle>تنظیمات ربات و پرداخت</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button asChild variant="outline"><Link href="/bots">تنظیمات ربات‌ها</Link></Button>
          <Button asChild variant="outline"><Link href="/payment-accounts">حساب‌های پرداخت</Link></Button>
        </CardContent>
      </Card>}
    </div>
  );
}
