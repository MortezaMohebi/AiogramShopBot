import { notFound } from "next/navigation";
import { createCampaign } from "@/app/(console)/campaigns/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { currentStaff } from "@/lib/bridge";

/** Only marketing staff can create a new, deliberately unsent campaign. */
export default async function NewCampaignPage() {
  const staff = await currentStaff();
  if (!["superadmin", "marketing"].includes(staff.role)) notFound();
  return (
    <div>
      <PageHeading title="کمپین جدید" description="ساخت پیش‌نویس؛ مخاطبان تا زمان تأیید مدیر و شروع مستقل Worker هیچ پیامی دریافت نمی‌کنند." />
      <Card className="max-w-3xl">
        <CardHeader><CardTitle>پیام Broadcast</CardTitle><CardDescription>متن فارسی و انتخاب پیام‌رسان، بدون اطلاعات ثابت در سورس.</CardDescription></CardHeader>
        <CardContent>
          <form action={createCampaign} className="space-y-5">
            <label className="block space-y-2 text-sm font-medium">عنوان داخلی کمپین
              <Input name="title" minLength={1} maxLength={120} required />
            </label>
            <label className="block space-y-2 text-sm font-medium">متن اعلان
              <Textarea name="text" minLength={1} maxLength={3000} required rows={8} />
            </label>
            <label className="block space-y-2 text-sm font-medium">مخاطبان
              <select name="audience" className="h-10 w-full rounded-md border border-input bg-background px-3">
                <option value="all">مشتریان دارای رضایت، در هر دو پیام‌رسان</option>
                <option value="telegram">فقط تلگرام</option>
                <option value="bale">فقط بله</option>
              </select>
            </label>
            <p className="text-xs leading-7 text-muted-foreground">رسانه‌های کمپین هنوز از داشبورد قدیمی بارگذاری می‌شوند؛ این فرم فقط پیش‌نویس مشترک ایجاد می‌کند.</p>
            <Button type="submit">ساخت پیش‌نویس</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
