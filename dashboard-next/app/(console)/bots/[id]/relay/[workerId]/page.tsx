import Link from "next/link";
import { notFound } from "next/navigation";
import { activateRelayRoute, pauseRelayRoute, removeRelayRoute, revokeRelayCredential, saveRelayPriority, stageRelayCredential } from "../../relay-actions";
import { DraftForm } from "@/components/blocks/draft-form";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, adminFetch, currentStaff } from "@/lib/bridge";
import type { BotRegistryDetail } from "@/lib/bot-registry";
import { relayId, relayMessage, relayRouteLabel, type BotRelaySnapshot, type RelayWorkersSnapshot } from "@/lib/relay-pool";

const resultText: Record<string, string> = {
  assigned: "مسیر اضافه شد. کلید اختصاصی را ثبت کنید.",
  staged: "کلید ثبت شد. همین نسخه را در Worker تنظیم کنید و اتصال را آزمایش کنید.",
  activate: "هویت ربات با پاسخ تلگرام تأیید شد و مسیر فعال است.",
  pause: "مسیر متوقف شد.",
  revoke: "کلید در رجیستری لغو شد.",
};

export default async function BotRelayRecord({ params, searchParams }: {
  params: Promise<{ id: string; workerId: string }>;
  searchParams: Promise<{ saved?: string; error?: string }>;
}) {
  const { id, workerId } = await params;
  if (!relayId(id) || !relayId(workerId) || (await currentStaff()).role !== "superadmin") notFound();
  const [detail, routes, workers] = await Promise.all([
    adminFetch<BotRegistryDetail>(`/bot-registry/${id}`),
    adminFetch<BotRelaySnapshot>(`/bot-registry/${id}/relay-routes`),
    adminFetch<RelayWorkersSnapshot>(`/bot-registry/${id}/relay-workers`),
  ]).catch(error => {
    if (error instanceof ApiError && [403, 404].includes(error.status)) notFound();
    throw error;
  });
  const route = routes.items.find(item => item.worker_id === workerId);
  if (!route || detail.bot.platform !== "telegram") notFound();
  const { saved, error } = await searchParams;
  const status = relayRouteLabel(route, workers.enabled);
  const canTest = workers.enabled && route.worker_status !== "disabled" && route.credential_version &&
    (route.credential_state === "staged" || (route.status === "paused" && route.credential_state === "active"));
  const keys = route.credential_history.filter(key => key.state === "staged" || key.state === "retiring");
  const ids = <>
    <input type="hidden" name="bot_id" value={id} />
    <input type="hidden" name="worker_id" value={workerId} />
  </>;
  const version = <>{ids}<input type="hidden" name="expected_version" value={route.version} /></>;
  return <div className="space-y-5">
    <PageHeading title={route.worker_name}
      description={detail.bot.name}
      action={<Button asChild size="sm" variant="outline"><Link href={`/bots/${id}#bot-relays`}>بازگشت به مسیرها</Link></Button>} />
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <Badge tone={status === "متصل" ? "success" : "neutral"}>{status}</Badge>
      {route.credential_verified_at && <span>آخرین تأیید {new Date(route.credential_verified_at).toLocaleString("fa-IR")}</span>}
      {!workers.enabled && <Link href="/services" className="text-primary underline">سرویس Relay خاموش است</Link>}
    </div>
    {error && <p role="alert" className="text-sm text-destructive">{relayMessage(error)}</p>}
    {saved && Object.hasOwn(resultText, saved) && <p role="status" className="text-sm">{resultText[saved]}</p>}
    <Card><CardHeader><CardTitle>اتصال تلگرام</CardTitle></CardHeader><CardContent className="space-y-4 text-sm">
      {canTest ? <PasswordActionForm action={activateRelayRoute} title="آزمون و فعال‌سازی مسیر"
        description="هویت ربات از طریق همین Worker بررسی می‌شود.">
        {version}<input type="hidden" name="credential_version" value={route.credential_version ?? ""} />
        <Button type="submit">آزمون و فعال‌سازی</Button>
      </PasswordActionForm> : route.status === "staged" && !route.credential_version ?
        <p>برای آزمون، کلید اختصاصی این مسیر را ثبت کنید.</p> : null}
      {route.status === "active" && <PasswordActionForm action={pauseRelayRoute} title="توقف مسیر Relay">
        {version}<Button type="submit" variant="outline" size="sm">توقف مسیر</Button>
      </PasswordActionForm>}
      <details open={route.status === "staged" && !route.credential_version ? true : undefined}>
        <summary className="w-fit cursor-pointer font-medium hover:underline">کلید اتصال</summary>
        <div className="mt-3 space-y-3">
          {route.credential_version && <p>نسخهٔ کلید {route.credential_version.toLocaleString("fa-IR")}</p>}
          <PasswordActionForm action={stageRelayCredential} when="required" includePassword={false} className="flex flex-wrap items-end gap-3">
            {version}
            <label className="block min-w-0 flex-1 space-y-2">کلید تازه
              <Input name="secret" type="password" dir="ltr" minLength={32} maxLength={256} autoComplete="new-password" required />
            </label>
            <Button type="submit" variant="outline" size="sm">ثبت کلید</Button>
          </PasswordActionForm>
          {keys.map(key => <PasswordActionForm key={key.version} action={revokeRelayCredential} title="لغو کلید"
            description="ابتدا همین نسخه را از Secret در Cloudflare حذف کنید.">
            {ids}<input type="hidden" name="credential_version" value={key.version} />
            <Button type="submit" variant="ghost" size="sm">لغو نسخهٔ {key.version.toLocaleString("fa-IR")}</Button>
          </PasswordActionForm>)}
          <Link href="/relay-workers#relay-setup" className="text-primary underline">راهنمای تنظیم کلید در Cloudflare</Link>
        </div>
      </details>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>تنظیمات مسیر</CardTitle></CardHeader><CardContent className="space-y-4 text-sm">
      <DraftForm saveAction={saveRelayPriority} className="space-y-2">
        {version}
        <label className="block space-y-2">اولویت
          <Input name="priority" type="number" min={1} max={1000} defaultValue={route.priority} required className="w-24" />
        </label>
        <p className="text-xs text-muted-foreground">عدد کمتر زودتر انتخاب می‌شود.</p>
      </DraftForm>
      <PasswordActionForm action={removeRelayRoute} title="حذف مسیر از ربات"
        description={route.status === "active" && !routes.items.some(item =>
          item.worker_id !== workerId && item.status === "active" && item.worker_status === "active")
          ? "این آخرین مسیر فعال ربات است. برای ادامهٔ ارسال از Relay، مسیر جایگزین لازم است."
          : "این مسیر و کلید آن از دسترس این ربات خارج می‌شوند."}>
        {version}<Button type="submit" variant="destructive" size="sm">حذف مسیر</Button>
      </PasswordActionForm>
    </CardContent></Card>
  </div>;
}
