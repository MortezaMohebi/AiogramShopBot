import { notFound } from "next/navigation";
import { changeCampaign, reconcileDelivery } from "@/app/(console)/campaigns/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { statusLabel } from "@/lib/utils";

type Params = Promise<{ id: string }>;

interface Delivery {
  id: number;
  platform: string;
  user_id: string;
  completed_steps: number;
  last_error_code: string | null;
}

/** Explicit operator decisions; uncertain deliveries never auto-retry. */
export default async function CampaignDetailsPage({ params }: { params: Params }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const staff = await currentStaff();
  if (!["superadmin", "marketing"].includes(staff.role)) notFound();
  const [campaigns, deliveries] = await Promise.all([
    adminFetch<Array<{ id: number; title: string; status: string; paid_calls_reserved: number; max_paid_calls: number }>>("/campaigns"),
    adminFetch<Delivery[]>(`/campaigns/${id}/deliveries`),
  ]);
  const campaign = campaigns.find((item) => item.id === Number(id));
  if (!campaign) notFound();
  return (
    <div>
      <PageHeading title={`کمپین «${campaign.title}»`} description="بررسی دستی رسیدهای نامشخص و کنترل توقف؛ تغییر وضعیت پرداخت یا ارسال مجدد خودکار انجام نمی‌شود." />
      <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader><CardTitle>وضعیت ارسال</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Badge>{statusLabel(campaign.status)}</Badge>
            <p className="text-sm text-muted-foreground">درخواست‌های پولی رزروشده: {campaign.paid_calls_reserved} از {campaign.max_paid_calls}</p>
            {["approved", "sending", "paused", "needs_review"].includes(campaign.status) ? (
              <form action={changeCampaign} className="space-y-2">
                <input type="hidden" name="id" value={id} />
                <input type="hidden" name="action" value="cancel" />
                <Input name="confirmation" dir="ltr" required placeholder="CANCEL_CAMPAIGN" />
                <Button type="submit" variant="destructive">لغو باقی‌مانده کمپین</Button>
              </form>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>تحویل‌های نیازمند بررسی</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {deliveries.map((delivery) => (
              <div key={delivery.id} className="rounded-lg border border-border p-4">
                <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-semibold">گیرنده #{delivery.id} — {delivery.platform === "bale" ? "بله" : "تلگرام"}</p>
                  <Badge tone="warning">نامشخص</Badge>
                </div>
                <p className="mb-3 text-xs text-muted-foreground">پیام‌های تأییدشده: {delivery.completed_steps} · علت: {delivery.last_error_code ?? "نامشخص"}</p>
                <form action={reconcileDelivery} className="space-y-3">
                  <input type="hidden" name="campaign_id" value={id} />
                  <input type="hidden" name="delivery_id" value={delivery.id} />
                  <label className="block space-y-2 text-sm">نتیجه بررسی
                    <select name="resolution" className="h-10 w-full rounded-md border border-input bg-background px-3">
                      <option value="sent">تحویل با مدرک تأیید شد</option>
                      <option value="skipped">بدون تحویل؛ بستن رکورد</option>
                    </select>
                  </label>
                  <label className="block space-y-2 text-sm">مدرک / توضیح (حداقل ۱۲ نویسه)
                    <Textarea name="evidence" required minLength={12} maxLength={255} rows={3} />
                  </label>
                  <Input name="confirmation" required dir="ltr" placeholder="RECONCILE_DELIVERY" />
                  <Button variant="outline" type="submit">ثبت نتیجه در Audit</Button>
                </form>
              </div>
            ))}
            {!deliveries.length ? <p className="py-10 text-center text-sm text-muted-foreground">مورد نامشخصی در فهرست اخیر وجود ندارد.</p> : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
