import { notFound } from "next/navigation";
import { saveSettings, saveReferralPolicy } from "@/app/(console)/settings/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { ShopSettings } from "@/lib/types";

type Params = Promise<{ saved?: string; error?: string }>;

/** Admin-controlled brand, welcome, help and FAQ, shared by both bots. */
export default async function SettingsPage({ searchParams }: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [settings, policy, params] = await Promise.all([
    adminFetch<ShopSettings>("/settings"),
    adminFetch<{is_enabled: boolean; percent: number; min_order_irr: string; max_bonus_irr: string}>("/referral-policy"),
    searchParams,
  ]);
  return (
    <div>
      <PageHeading title="تنظیمات فروشگاه" description="متن خوش‌آمدگویی، پرسش‌های متداول و پشتیبانی، بدون تغییر کد هر دو پیام‌رسان." />
      {params.saved ? <p role="status" className="mb-4 rounded-lg bg-accent p-3 text-sm text-accent-foreground">تنظیمات ذخیره شد.</p> : null}
      {params.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">ذخیره انجام نشد؛ مقادیر یا دسترسی را بررسی کنید.</p> : null}
      <Card className="max-w-4xl">
        <CardHeader><CardTitle>محتوای مشترک</CardTitle><CardDescription>تغییرات بعد از ذخیره از پایگاه داده هر دو ربات خوانده می‌شوند.</CardDescription></CardHeader>
        <CardContent>
          <form action={saveSettings} className="space-y-5">
            <label className="block space-y-2 text-sm font-medium">نام فروشگاه
              <Input name="brand_name" maxLength={255} defaultValue={settings.brand_name ?? ""} />
            </label>
            <label className="block space-y-2 text-sm font-medium">پیام خوش‌آمدگویی
              <Textarea name="welcome_message" rows={5} maxLength={4096} defaultValue={settings.welcome_message ?? ""} />
            </label>
            <label className="block space-y-2 text-sm font-medium">پرسش‌های متداول
              <Textarea name="faq_text" rows={7} maxLength={20000} defaultValue={settings.faq_text ?? ""} />
            </label>
            <label className="block space-y-2 text-sm font-medium">لینک پشتیبانی (HTTPS)
              <Input name="support_url" dir="ltr" type="url" className="text-start" maxLength={500} defaultValue={settings.support_url ?? ""} placeholder="https://..." />
            </label>
            <Button type="submit">ذخیره تنظیمات</Button>
          </form>
        </CardContent>
      </Card>
      <Card className="mt-6 max-w-4xl">
        <CardHeader><CardTitle>سیاست پاداش معرفی مشتری</CardTitle><CardDescription>پاداش خرید اول از اعتبار داخلی فروشگاه تأمین می‌شود؛ هیچ موجودی بله یا رمز ارز تغییر نمی‌کند.</CardDescription></CardHeader>
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
            <div className="md:col-span-2"><Button type="submit">ذخیره سیاست معرفی</Button></div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
