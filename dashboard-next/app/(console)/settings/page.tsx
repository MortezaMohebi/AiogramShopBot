import { notFound } from "next/navigation";
import { saveSettings } from "@/app/(console)/settings/actions";
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
  const [settings, params] = await Promise.all([
    adminFetch<ShopSettings>("/settings"),
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
    </div>
  );
}
