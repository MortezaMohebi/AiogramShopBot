import { notFound } from "next/navigation";
import { changeCampaign, reconcileDelivery, deleteCampaignMedia, prepareBaleMedia } from "@/app/(console)/campaigns/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { statusLabel } from "@/lib/utils";
import { uploadErrorMessage } from "@/lib/upload-errors";

type Params = Promise<{ id: string }>;
type Query = Promise<{ saved?: string; error?: string }>;

interface CampaignFile {
  id: number; kind: string; filename: string; size_bytes: number;
  position: number; caption: string | null;
}

interface Delivery {
  id: number;
  platform: string;
  user_id: string;
  completed_steps: number;
  last_error_code: string | null;
}

/** Explicit operator decisions; uncertain deliveries never auto-retry. */
export default async function CampaignDetailsPage({ params, searchParams }: { params: Params; searchParams: Query }) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  if (!/^\d+$/.test(id)) notFound();
  const staff = await currentStaff();
  if (!["superadmin", "marketing"].includes(staff.role)) notFound();
  const [campaigns, deliveries, media, capabilities] = await Promise.all([
    adminFetch<Array<{ id: number; title: string; status: string; paid_calls_reserved: number; max_paid_calls: number }>>("/campaigns"),
    adminFetch<Delivery[]>(`/campaigns/${id}/deliveries`),
    adminFetch<{ can_edit: boolean; items: CampaignFile[] }>(`/campaigns/${id}/media`),
    adminFetch<{bale_prepare_ready: boolean}>("/capabilities"),
  ]);
  const campaign = campaigns.find((item) => item.id === Number(id));
  if (!campaign) notFound();
  return (
    <div>
      <PageHeading title={`کمپین «${campaign.title}»`} description="بررسی دستی رسیدهای نامشخص و کنترل توقف؛ تغییر وضعیت پرداخت یا ارسال مجدد خودکار انجام نمی‌شود." />
      {query.saved ? <p role="status" className="mb-5 rounded-lg bg-accent p-3 text-sm">عملیات مدیریت رسانه ثبت شد. وضعیت پرونده و فایل‌ها را بررسی کنید.</p> : null}
      {query.error ? <p role="alert" className="mb-5 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{uploadErrorMessage(query.error, "درخواست انجام نشد. وضعیت Draft، محدودیت فایل و مدارک عملیات را بررسی کنید. در وضعیت نامشخص بله، بدون بررسی دوباره تلاش نکنید.")}</p> : null}
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
      {capabilities.bale_prepare_ready && ["draft", "approved"].includes(campaign.status) && media.items.length > 0 ? (
        <Card className="mt-6">
          <CardHeader><CardTitle>آماده‌سازی رسانه برای بله</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">ارسال آزمایشی فایل‌ها فقط به چت خصوصی آماده‌سازی مدیر در بله از API معمولی انجام می‌شود. این کار کمپین را شروع نمی‌کند؛ در خطای نامشخص، وضعیت را بررسی کنید و کورکورانه تکرار نکنید.</p>
            <form action={prepareBaleMedia} className="flex flex-wrap items-center gap-3">
              <input name="campaign_id" type="hidden" value={id} />
              <Input name="confirmation" dir="ltr" placeholder="PREPARE_BALE_MEDIA" required className="max-w-60 text-xs" />
              <Button type="submit" variant="secondary">آماده‌سازی فایل‌های بله در چت خصوصی</Button>
            </form>
          </CardContent>
        </Card>
      ) : null}
      <Card className="mt-6">
        <CardHeader><CardTitle>رسانه‌های کمپین</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">فایل‌ها به‌ترتیب ارسال می‌شوند و پس از تأیید مخاطبان دیگر قابل تغییر نیستند.</p>
          {media.can_edit ? (
            <form method="post" encType="multipart/form-data" action="/api/admin/upload?target=campaign" className="grid gap-3 md:grid-cols-[1fr_1fr_7rem_auto] md:items-end">
              <input type="hidden" name="campaign_id" value={id} />
              <label className="space-y-2 text-xs">فایل
                <Input type="file" name="file" accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,audio/mpeg,audio/ogg,application/pdf" required />
              </label>
              <label className="space-y-2 text-xs">توضیح
                <Input name="caption" maxLength={1024} />
              </label>
              <label className="space-y-2 text-xs">ترتیب
                <Input type="number" name="position" min={0} max={1000000} defaultValue={0} required />
              </label>
              <Button type="submit">بارگذاری</Button>
            </form>
          ) : null}
          {media.items.map((file) => (
            <div key={file.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border p-3">
              <div className="min-w-0">
                <p className="break-all text-sm" dir="ltr">{file.filename}</p>
                <p className="text-xs text-muted-foreground">{file.kind} · {(file.size_bytes / 1000000).toFixed(1)} MB · ترتیب {file.position}</p>
                {file.caption ? <p className="text-xs">{file.caption}</p> : null}
              </div>
              <div className="flex items-center gap-2">
                <a className="text-sm text-primary underline" target="_blank" rel="noopener noreferrer" href={`/api/admin/preview/campaign/${file.id}`}>پیش‌نمایش</a>
                {media.can_edit ? (
                  <form action={deleteCampaignMedia} className="flex flex-wrap items-center gap-2">
                    <input type="hidden" name="campaign_id" value={id} />
                    <input type="hidden" name="media_id" value={file.id} />
                    <Input name="confirmation" required dir="ltr" placeholder="DELETE_DRAFT_ATTACHMENT" aria-label="عبارت تأیید حذف" className="w-52 text-xs" />
                    <Button type="submit" size="sm" variant="destructive">حذف</Button>
                  </form>
                ) : null}
              </div>
            </div>
          ))}
          {!media.items.length ? <p className="text-sm text-muted-foreground">هیچ فایلی به کمپین پیوست نشده است.</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}
