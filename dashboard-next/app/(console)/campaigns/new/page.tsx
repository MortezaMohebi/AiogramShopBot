import { notFound } from "next/navigation";
import { createCampaign } from "@/app/(console)/campaigns/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { CampaignBotOptions } from "@/lib/campaigns";

/** Only marketing staff can create a new, deliberately unsent campaign. */
export default async function NewCampaignPage() {
  const staff = await currentStaff();
  if (!["superadmin", "marketing"].includes(staff.role)) notFound();
  const options = await adminFetch<CampaignBotOptions>("/campaigns/bots");
  const hasSender = options.bots.length > 0;
  return (
    <div>
      <PageHeading title="کمپین جدید" description="ساخت پیش‌نویس، پیامی ارسال نمی‌کند. مخاطبان و شروع ارسال جداگانه تأیید می‌شوند." />
      <Card className="max-w-3xl">
        <CardHeader><CardTitle>پیام کمپین</CardTitle><CardDescription>فروشگاه: {options.store_name}. پیام فقط برای مشتریان دارای رضایتِ ربات انتخاب‌شده آماده می‌شود.</CardDescription></CardHeader>
        <CardContent>
          <form action={createCampaign} className="space-y-5">
            <label className="block space-y-2 text-sm font-medium">عنوان داخلی کمپین
              <Input name="title" minLength={1} maxLength={120} required />
            </label>
            <label className="block space-y-2 text-sm font-medium">متن اعلان
              <Textarea name="text" minLength={1} maxLength={3000} required rows={8} />
            </label>
            <label className="block space-y-2 text-sm font-medium">ربات ارسال‌کننده
              <select name="target" required defaultValue="" disabled={!hasSender} className="h-10 w-full rounded-md border border-input bg-background px-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                <option value="" disabled>ربات را انتخاب کنید</option>
                {options.bots.map((bot) => (
                  <option key={bot.id} value={bot.id}>{bot.name} — {bot.platform === "bale" ? "بله" : "تلگرام"}</option>
                ))}
              </select>
            </label>
            {!hasSender ? <p role="status" className="text-sm text-muted-foreground">برای این فروشگاه ربات فعالی در دسترس نیست. پس از فعال‌شدن ربات، می‌توانید پیش‌نویس بسازید.</p> : null}
            <p className="text-xs leading-7 text-muted-foreground">پس از ساخت پیش‌نویس، فایل‌ها را در صفحهٔ جزئیات اضافه کنید. سپس مخاطبان را تأیید و ارسال را شروع کنید.</p>
            <Button type="submit" disabled={!hasSender}>ساخت پیش‌نویس</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
