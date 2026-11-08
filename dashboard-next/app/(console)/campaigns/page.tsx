import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { Megaphone, Plus, ShieldAlert } from "lucide-react";
import { changeCampaign } from "@/app/(console)/campaigns/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { Campaign } from "@/lib/campaigns";
import { statusLabel } from "@/lib/utils";

interface Capabilities {
  broadcast_worker_enabled: boolean;
  broadcast_registry_enabled: boolean;
  bale_business_enabled: boolean;
  max_paid_calls: number;
}

type Params = Promise<{ saved?: string; error?: string }>;

/** Durable Broadcast dashboard; no synchronous send_batch HTTP endpoint. */
export default async function CampaignsPage({ searchParams }: { searchParams: Params }) {
  const [campaigns, capabilities, staff, params] = await Promise.all([
    adminFetch<Campaign[]>("/campaigns"),
    adminFetch<Capabilities>("/capabilities"),
    currentStaff(),
    searchParams,
  ]);
  const manage = ["superadmin", "marketing"].includes(staff.role);

  return (
    <div>
      <PageHeading
        title="کمپین‌های پیام‌رسانی"
        description="پیام‌ها فقط برای مشتریان دارای رضایت ارسال می‌شوند."
        action={manage ? <Button asChild><Link href="/campaigns/new"><Plus /> ساخت کمپین</Link></Button> : undefined}
      />
      {params.saved ? <p role="status" className="mb-4 rounded-lg bg-accent px-4 py-3 text-sm text-accent-foreground">تغییرات کمپین ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="mb-4 rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">{params.error === "create" ? "پیش‌نویس ساخته نشد. ربات فعال و دسترسی نوشتن در فروشگاه فعلی را بررسی کنید." : "درخواست اجرا نشد. عبارت تأیید، فروشگاه فعلی، وضعیت کمپین، فعال‌بودن ارسال خودکار و محدودیت پرداخت را بررسی کنید."}</p> : null}
      <div className="mb-6 flex flex-wrap gap-3 rounded-xl border border-border bg-card p-4 text-sm">
        <span className={capabilities.broadcast_worker_enabled ? "text-emerald-600 dark:text-emerald-300" : "text-amber-700 dark:text-amber-300"}>
          <b>ارسال خودکار:</b> {capabilities.broadcast_worker_enabled ? "مجوز اجرا فعال" : "غیرفعال"}
        </span>
        <span className="text-muted-foreground">Business بله: {capabilities.bale_business_enabled ? "قابل انتخاب، هزینه‌دار" : "غیرفعال"}</span>
        <span className="text-muted-foreground">سقف درخواست پولی: {capabilities.max_paid_calls}</span>
      </div>
      <div className="grid gap-4">
        {campaigns.map((campaign) => {
          const count = campaign.counts;
          const total = Object.values(count).reduce((sum, n) => sum + n, 0);
          const done = (count.sent ?? 0) + (count.skipped ?? 0);
          const progress = total ? Math.round((done / total) * 100) : 0;
          const requiredPaid = campaign.bale_recipients * (1 + campaign.media_count);
          const canStart = capabilities.broadcast_worker_enabled && (
            campaign.bot_id === null || capabilities.broadcast_registry_enabled
          );
          return (
            <RecordClickArea as="section" key={campaign.id} className="rounded-xl border border-border bg-card text-card-foreground shadow-sm hover:bg-muted/30">
              <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-2">
                <div>
                  <CardTitle><RecordLink href={`/campaigns/${campaign.id}`}>{campaign.title}</RecordLink></CardTitle>
                  <p className="mt-2 text-xs text-muted-foreground">
                    #{campaign.id} · {campaign.bot_id ? "مشتریان همین ربات" : campaign.audience === "all" ? "هر دو پیام‌رسان" : campaign.audience === "bale" ? "بله" : "تلگرام"}
                    {" · "}{total} مخاطب
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    فروشگاه: {campaign.store_name} · ربات: {campaign.bot_id ? `${campaign.bot_name ?? "ربات انتخاب‌شده"} (${campaign.bot_platform === "bale" ? "بله" : "تلگرام"})` : "ربات‌های قدیمی فروشگاه"}
                  </p>
                </div>
                <Badge tone={campaign.status === "completed" ? "success" : campaign.status === "needs_review" ? "danger" : campaign.status === "sending" ? "warning" : "neutral"}>
                  {statusLabel(campaign.status)}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  aria-label={`پیشرفت کمپین ${campaign.title}`}
                  role="progressbar"
                  aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}
                  className="h-2.5 overflow-hidden rounded-full bg-muted"
                >
                  <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
                </div>
                <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                  <span>ارسال‌شده: {count.sent ?? 0}</span>
                  <span>در صف: {count.queued ?? 0}</span>
                  <span>نامشخص: {count.unknown ?? 0}</span>
                  <span>فایل: {campaign.media_count}</span>
                  {campaign.bale_mode === "business" ? <span>درخواست پولی: {campaign.paid_calls_reserved}/{campaign.max_paid_calls}</span> : null}
                </div>
                <div className="flex flex-wrap items-end gap-3 empty:hidden">
                  {manage && campaign.status === "draft" ? (
                    <form action={changeCampaign} className="flex items-end gap-2">
                      <input type="hidden" name="id" value={campaign.id} />
                      <input type="hidden" name="action" value="approve" />
                      <Input name="confirmation" required placeholder="APPROVE_CAMPAIGN" aria-label="عبارت تأیید مخاطبان" className="max-w-56 text-xs" dir="ltr" />
                      <Button size="sm" type="submit">تأیید مخاطبان</Button>
                    </form>
                  ) : null}
                  {manage && campaign.status === "approved" ? (
                    <form action={changeCampaign} className="flex flex-wrap items-end gap-2">
                      <input type="hidden" name="id" value={campaign.id} />
                      <input type="hidden" name="action" value="start" />
                      <label className="space-y-1 text-xs">حالت بله
                        <select name="bale_mode" className="block h-9 rounded-md border border-input bg-background px-2 text-sm">
                          <option value="standard">Standard</option>
                          {capabilities.bale_business_enabled ? <option value="business">Business (هزینه‌دار)</option> : null}
                        </select>
                      </label>
                      <label className="space-y-1 text-xs">سقف درخواست پولی (Business: {requiredPaid})
                        <Input name="approved_paid_calls" type="number" min={0} max={capabilities.max_paid_calls} defaultValue={0} className="w-40" />
                      </label>
                      <Input name="confirmation" aria-label="عبارت تأیید عملیات" dir="ltr" required placeholder="START_CAMPAIGN / START_PAID_BALE" className="max-w-60 text-xs" />
                      <Button size="sm" disabled={!canStart} type="submit">شروع خودکار</Button>
                      {!canStart && campaign.bot_id !== null ? <p className="w-full text-xs text-muted-foreground">ارسال برای این ربات هنوز فعال نشده است.</p> : null}
                    </form>
                  ) : null}
                  {manage && ["sending", "paused"].includes(campaign.status) ? (
                    <form action={changeCampaign} className="flex flex-wrap items-center gap-2">
                      <input type="hidden" name="id" value={campaign.id} />
                      <input type="hidden" name="action" value={campaign.status === "sending" ? "pause" : "resume"} />
                      <Input name="confirmation" aria-label="عبارت تأیید عملیات" dir="ltr" required placeholder={campaign.status === "sending" ? "PAUSE_CAMPAIGN" : "RESUME_CAMPAIGN"} className="max-w-52 text-xs" />
                      <Button size="sm" variant="secondary" type="submit">{campaign.status === "sending" ? "توقف" : "ادامه"}</Button>
                    </form>
                  ) : null}
                </div>
              </CardContent>
            </RecordClickArea>
          );
        })}
        {!campaigns.length ? (
          <Card><CardContent className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
            <Megaphone className="size-10" />
            <p className="font-semibold">هنوز کمپینی تعریف نشده است.</p>
            <p className="text-sm">برای آماده‌کردن پیام و انتخاب ربات، کمپین بسازید.</p>
          </CardContent></Card>
        ) : null}
      </div>
      <p className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
        <ShieldAlert className="size-4 shrink-0" />
        هیچ پیامی بدون فعال‌بودن تنظیمات ارسال و تأیید صریح مدیر فرستاده نمی‌شود.
      </p>
    </div>
  );
}
