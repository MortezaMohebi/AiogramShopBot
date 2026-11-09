import Link from "next/link";
import { notFound } from "next/navigation";
import { changeRelayOrigin, removeRelayWorker, saveRelayWorker, setRelayWorkerState } from "../actions";
import { DraftForm } from "@/components/blocks/draft-form";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { RelayWorkerFields } from "@/components/blocks/relay-worker-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, adminFetch, currentStaff } from "@/lib/bridge";
import { relayId, relayMessage, relayWorkerLabels, type RelayWorker } from "@/lib/relay-pool";

export default async function RelayWorkerPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ error?: string; saved?: string }>;
}) {
  const { id } = await params;
  if (!relayId(id) || (await currentStaff()).role !== "superadmin") notFound();
  const worker = await adminFetch<RelayWorker>(`/relay-workers/${id}`).catch(error => {
    if (error instanceof ApiError && [403, 404, 409].includes(error.status)) notFound();
    throw error;
  });
  const { error, saved } = await searchParams;
  const version = <>
    <input type="hidden" name="worker_id" value={worker.id} />
    <input type="hidden" name="expected_version" value={worker.version} />
  </>;
  return <div className="space-y-5">
    <PageHeading title={worker.name} action={<Button asChild variant="outline" size="sm"><Link href="/relay-workers">بازگشت به فهرست</Link></Button>} />
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Badge tone={worker.status === "active" ? "success" : "neutral"}>{relayWorkerLabels[worker.status]}</Badge>
      <span>{worker.bot_count.toLocaleString("fa-IR")} ربات متصل</span>
      <bdi className="min-w-0 break-all text-muted-foreground">{worker.origin}</bdi>
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{relayMessage(error)}</p>}
    {saved && <p role="status" className="text-sm">{saved === "created" ? "Worker ثبت شد. آن را به یک ربات تلگرام متصل کنید." :
      saved === "origin" ? "نشانی ذخیره شد. برای مسیرها کلید تازه ثبت و اتصال را آزمایش کنید." : "وضعیت Worker ذخیره شد."}</p>}
    <Card><CardHeader><CardTitle>مشخصات Worker</CardTitle></CardHeader><CardContent>
      <DraftForm saveAction={saveRelayWorker} className="grid gap-4 sm:grid-cols-2" footerClassName="sm:col-span-2">
        {version}<RelayWorkerFields worker={worker} />
      </DraftForm>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>اتصال و وضعیت</CardTitle></CardHeader><CardContent className="space-y-4 text-sm">
      {worker.status !== "draft" && <PasswordActionForm action={setRelayWorkerState} title="تغییر وضعیت Worker" className="flex flex-wrap items-end gap-2">
        {version}
        <label className="space-y-2">وضعیت
          <select name="state" defaultValue={worker.status} className="block h-10 rounded-md border bg-background px-3">
            {Object.entries(relayWorkerLabels).filter(([value]) => value !== "draft").map(([value, label]) =>
              <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <Button type="submit" variant="outline">اعمال وضعیت</Button>
      </PasswordActionForm>}
      <details>
        <summary className="w-fit cursor-pointer font-medium hover:underline">تغییر نشانی Worker</summary>
        <PasswordActionForm action={changeRelayOrigin} title="تغییر نشانی Worker"
          description="با تغییر نشانی، کلیدهای قبلی کنار گذاشته می‌شوند و مسیرها به آزمون دوباره نیاز دارند."
          className="mt-3 space-y-3">
          {version}
          {Object.entries({ name: worker.name, slug: worker.slug, max_rps: worker.max_rps, max_inflight: worker.max_inflight }).map(([name, value]) =>
            <input key={name} type="hidden" name={name} value={value} />)}
          <label className="block space-y-2">نشانی تازه
            <Input name="origin" type="url" dir="ltr" defaultValue={worker.origin} required maxLength={300} />
          </label>
          <Button type="submit" variant="outline">تغییر نشانی</Button>
        </PasswordActionForm>
      </details>
      <PasswordActionForm action={removeRelayWorker} title="حذف Worker از رجیستری"
        description={worker.bot_count ? "همهٔ اتصال‌های این Worker حذف می‌شوند. ربات بدون مسیر جایگزین از طریق Relay ارسال نمی‌کند." :
          "این ثبت حذف می‌شود. Worker در Cloudflare باقی می‌ماند."}>
        {version}<Button type="submit" variant="destructive" size="sm">حذف Worker</Button>
      </PasswordActionForm>
    </CardContent></Card>
  </div>;
}
