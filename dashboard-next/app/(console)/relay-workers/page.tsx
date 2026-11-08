import { StoreScopeNotice } from "@/components/blocks/store-scope-notice";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Boxes, Webhook } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { optionalStoreRead, currentStaff } from "@/lib/bridge";
import type { RelayWorkersSnapshot } from "@/lib/relay-pool";
import {
  createRelayWorker, setRelayWorkerState,
} from "@/app/(console)/relay-workers/actions";

type Query = Promise<{ saved?: string; error?: string }>;

const messages: Record<string, string> = {
  validation: "مقادیر واردشده معتبر نیستند.",
  reauth: "برای اعمال تغییر امنیتی باید هویت مدیر دوباره تأیید شود.",
  invalid_relay_worker: "شناسه، نام یا محدودیت ظرفیت معتبر نیست.",
  relay_worker_exists: "Worker با این شناسه یا آدرس قبلاً تعریف شده است.",
  configuration_changed: "نسخهٔ تنظیمات تغییر کرده؛ صفحه را تازه‌سازی کنید.",
  transport_endpoint_not_approved: "دامنهٔ Worker در Allowlist سرور نیست.",
  relay_worker_not_verified: "حداقل یک Route تأییدشده برای این Worker لازم است.",
  invalid_credentials: "تأیید رمز مدیر موفق نبود.",
  invalid_verification: "کد MFA معتبر نیست.",
  save: "ذخیره انجام نشد؛ سرویس و مجوزها را بررسی کنید.",
};

/** Superadmin-only view: no relay secret or provider token is serialized. */
export default async function RelayWorkersPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();

  const query = await searchParams;
  const data = await optionalStoreRead<RelayWorkersSnapshot>("/relay-workers");
  if (!data) return <StoreScopeNotice title="سرویس‌های Relay" />;
  return <div className="space-y-6">
    <PageHeading title="سرویس‌های Relay" />
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <Link href="/bots">مدیریت ربات‌ها</Link>
      </Button>
      <Button asChild variant="outline" size="sm">
        <Link href="/bots">تنظیمات ربات‌ها</Link>
      </Button>
    </div>
    <div className="rounded-xl border p-4 text-sm leading-7">
      <p>وضعیت Relay: <strong>
        {data.enabled ? "فعال؛ فقط مسیرهای تأییدشده استفاده می‌شوند" : "در بخش سرویس‌ها متوقف است"}
      </strong></p>
      <p>این پنل Worker را Deploy نمی‌کند و Secret را به Cloudflare ارسال نمی‌کند.
        ابتدا Secret هر ربات را جداگانه در Cloudflare پیکربندی کنید؛
        سپس از صفحهٔ ربات، مسیر را با getMe و MFA تأیید کنید.</p>
      <p>ظرفیت‌های ثبت‌شده در این صفحه سیاست مدیریت‌اند؛ محدودیت سخت در Cloudflare
        با Durable Object و تنظیمات RELAY_CLIENTS_JSON اعمال می‌شود.</p>
    </div>
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      تغییرات ثبت شدند. فعال‌شدن Worker بدون تأیید مسیر ربات انجام نمی‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      {messages[query.error] ?? messages.save}
    </p> : null}
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <Webhook className="size-5" /> Workerهای ثبت‌شده
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        {data.items.length ? <div className="overflow-x-auto">
          <table className="w-full min-w-[740px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نام</th><th className="p-3">آدرس HTTPS</th>
              <th className="p-3">ربات‌ها</th><th className="p-3">سیاست ظرفیت</th>
              <th className="p-3">وضعیت</th>
            </tr></thead>
            <tbody>{data.items.map(worker => <tr key={worker.id} className="border-b">
              <td className="p-3 font-medium">{worker.name}<span className="block text-xs text-muted-foreground">{worker.slug}</span></td>
              <td className="p-3" dir="ltr">{worker.origin}</td>
              <td className="p-3">{worker.bot_count}</td>
              <td className="p-3">{worker.max_rps} درخواست/ثانیه · {worker.max_inflight} هم‌زمان</td>
              <td className="p-3"><Badge tone={worker.status === "active" ? "success" : "neutral"}>{({ active: "فعال", paused: "متوقف", disabled: "غیرفعال", draft: "پیش‌نویس", archived: "بایگانی‌شده" } as Record<string, string>)[worker.status] ?? worker.status}</Badge></td>
            </tr>)}</tbody>
          </table>
        </div> : <p className="text-sm text-muted-foreground">هنوز Worker ثبت نشده است. از فرم زیر Worker اضافه کنید.</p>}
        {data.items.filter(worker => worker.status !== "draft").map(worker => <form
          key={worker.id} action={setRelayWorkerState}
          className="grid gap-3 rounded-xl border p-3 lg:grid-cols-[1fr_auto_1fr_1fr_auto] lg:items-end">
          <input type="hidden" name="worker_id" value={worker.id} />
          <input type="hidden" name="expected_version" value={worker.version} />
          <label className="block space-y-2 text-sm">{worker.name} — وضعیت هدف
            <select name="state" defaultValue={worker.status}
              className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="active">فعال</option>
              <option value="paused">متوقف</option>
              <option value="disabled">غیرفعال</option>
            </select>
          </label>
          <span className="text-xs text-muted-foreground">نسخهٔ {worker.version}</span>
          <label className="block space-y-2 text-sm">رمز فعلی
            <Input name="current_password" type="password" required autoComplete="current-password" />
          </label>
          <label className="block space-y-2 text-sm">کد MFA
            <Input name="second_factor" dir="ltr" inputMode="numeric" pattern="[0-9]{6}"
              maxLength={6} autoComplete="one-time-code" required />
          </label>
          <Button type="submit" variant="outline">تغییر وضعیت</Button>
        </form>)}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <Boxes className="size-5" /> ثبت Worker جدید
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-7">قبل از ثبت، آدرس Worker باید در متغیر
          TELEGRAM_WORKER_ALLOWED_ORIGINS سرور مجاز شده باشد. ثبت Worker به‌تنهایی آن را فعال نمی‌کند.</p>
        <form action={createRelayWorker} className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2 text-sm">نام نمایشی
            <Input name="name" maxLength={160} required placeholder="Relay Tokyo" />
          </label>
          <label className="space-y-2 text-sm">Slug یکتا
            <Input name="slug" pattern="[a-z][a-z0-9\-]{2,63}"
              minLength={3} maxLength={64} required dir="ltr" placeholder="relay-tokyo" />
          </label>
          <label className="space-y-2 text-sm sm:col-span-2">آدرس Worker (HTTPS)
            <Input name="origin" type="url" dir="ltr" required
              placeholder="https://relay.example.workers.dev" maxLength={300} />
          </label>
          <label className="space-y-2 text-sm">سقف درخواست بر ثانیه
            <Input name="max_rps" type="number" min={1} max={20} defaultValue={5} required />
          </label>
          <label className="space-y-2 text-sm">سقف اتصال هم‌زمان
            <Input name="max_inflight" type="number" min={1} max={50} defaultValue={10} required />
          </label>
          <div className="sm:col-span-2">
            <Button type="submit">ثبت Worker</Button>
          </div>
        </form>
      </CardContent>
    </Card>
  </div>;
}
