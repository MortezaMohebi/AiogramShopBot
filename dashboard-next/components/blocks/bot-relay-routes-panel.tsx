import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { BotRecord } from "@/lib/bot-registry";
import type {
  BotRelayRoute, BotRelaySnapshot, RelayWorkersSnapshot,
} from "@/lib/relay-pool";
import {
  activateRelayRoute, assignRelayRoute, pauseRelayRoute,
  revokeRelayCredential, stageRelayCredential,
} from "@/app/(console)/bots/[id]/relay-actions";

interface Props {
  bot: BotRecord;
  workers: RelayWorkersSnapshot;
  routes: BotRelaySnapshot;
}

function CredentialProof() {
  return <div className="grid gap-3 sm:grid-cols-2">
    <label className="block space-y-2 text-sm">رمز فعلی مدیر
      <Input name="current_password" type="password"
        autoComplete="current-password" maxLength={256} required />
    </label>
    <label className="block space-y-2 text-sm">کد MFA
      <Input name="second_factor" inputMode="numeric" pattern="[0-9]{6}"
        maxLength={6} autoComplete="one-time-code" required />
    </label>
  </div>;
}

function RouteControls({
  bot, route, enabled,
}: { bot: BotRecord; route: BotRelayRoute; enabled: boolean }) {
  const canActivate = Boolean(
    enabled && route.credential_state === "staged" &&
    route.credential_version && route.worker_status !== "disabled",
  );
  return <div className="space-y-4 rounded-xl border p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="font-semibold">{route.worker_name}</p>
      <p className="text-xs text-muted-foreground">
        اولویت {route.priority} · {route.status} · نسخه {route.version}
      </p>
    </div>
    <p className="text-xs text-muted-foreground">
      وضعیت Worker: {route.worker_status} · آخرین کلید:
      {route.credential_version ?? "ثبت نشده"} ({route.credential_state ?? "—"})
    </p>
    {route.status !== "active" ? <form action={assignRelayRoute}
      className="flex flex-wrap items-end gap-3">
      <input type="hidden" name="bot_id" value={bot.id} />
      <input type="hidden" name="worker_id" value={route.worker_id} />
      <input type="hidden" name="expected_version" value={route.version} />
      <label className="space-y-2 text-sm">ویرایش اولویت
        <Input name="priority" type="number" min={1} max={1000}
          defaultValue={route.priority} required />
      </label>
      <Button type="submit" variant="outline">ثبت اولویت</Button>
    </form> : null}

    <form action={stageRelayCredential} className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
      <input type="hidden" name="bot_id" value={bot.id} />
      <input type="hidden" name="worker_id" value={route.worker_id} />
      <label className="block space-y-2 text-sm">
        Secret مستقل همین بات در این Worker
        <Input name="secret" type="password" minLength={32} maxLength={256}
          autoComplete="new-password" dir="ltr" required
          placeholder="همان کلید نسخه‌دار در Cloudflare Secret" />
      </label>
      <Button type="submit" variant="outline">Stage کلید جدید</Button>
    </form>
    {canActivate ? <form action={activateRelayRoute}
      className="space-y-3 rounded-lg border p-3">
      <p className="text-sm leading-7">پس از Provision همان Version و Token SHA-256 در Cloudflare،
        getMe تأییدشده اجرا می‌شود. این مرحله فقط Key و Route را فعال می‌کند؛
        هیچ پیام یا پرداختی ارسال نمی‌شود.</p>
      <input type="hidden" name="bot_id" value={bot.id} />
      <input type="hidden" name="worker_id" value={route.worker_id} />
      <input type="hidden" name="expected_version" value={route.version} />
      <input type="hidden" name="credential_version" value={route.credential_version ?? ""} />
      <CredentialProof />
      <Button type="submit">تأیید getMe و فعال‌سازی مسیر</Button>
    </form> : null}
    {route.status === "active" ? <form action={pauseRelayRoute}
      className="space-y-3 rounded-lg border p-3">
      <p className="text-sm leading-7">Pause فقط ارسالهای جدید را از این مسیر برمی‌دارد.
        ارسال دارای نتیجهٔ نامشخص روی Worker دیگری تکرار نمی‌شود.</p>
      <input type="hidden" name="bot_id" value={bot.id} />
      <input type="hidden" name="worker_id" value={route.worker_id} />
      <input type="hidden" name="expected_version" value={route.version} />
      <CredentialProof />
      <Button type="submit" variant="outline">توقف انتخاب این مسیر</Button>
    </form> : null}
    {route.credential_state === "staged" && route.credential_version ? <form
      action={revokeRelayCredential} className="space-y-3 rounded-lg border p-3">
      <input type="hidden" name="bot_id" value={bot.id} />
      <input type="hidden" name="worker_id" value={route.worker_id} />
      <input type="hidden" name="version" value={route.credential_version} />
      <p className="text-xs leading-6">لغو نسخهٔ Staged فقط پس از حذف آن از
        RELAY_CLIENTS_JSON در Worker نهایی می‌شود.</p>
      <CredentialProof />
      <Button type="submit" variant="outline">لغو نسخهٔ Staged</Button>
    </form> : null}
  </div>;
}

/** Show authenticated many-to-many routing without exposing keys or Bot API tokens. */
export function BotRelayRoutesPanel({ bot, workers, routes }: Props) {
  if (bot.runtime_owner !== "registry" || bot.platform !== "telegram") {
    return null;
  }
  const assignedIds = new Set(routes.items.map(row => row.worker_id));
  const available = workers.items.filter(row =>
    !assignedIds.has(row.id) && row.status !== "disabled",
  );
  return <Card>
    <CardHeader><CardTitle>اتصال بات به Relay Worker Pool</CardTitle></CardHeader>
    <CardContent className="space-y-5 text-sm">
      <p className="leading-7">هر بات می‌تواند چند Worker با اولویت متفاوت داشته باشد.
        هر Worker نیز هم‌زمان چند بات را با Secret مجزا مدیریت می‌کند.
        Failover صرفاً برای متدهای خواندنی و بدون Side Effect است.</p>
      <p>وضعیت Pool:
        <strong> {workers.enabled ? "فعال در سرور" : "خاموش در سرور"}</strong>
        {" "}· <Link href="/relay-workers" className="underline">فهرست Workerها و ظرفیت</Link>
      </p>
      {available.length ? <form action={assignRelayRoute}
        className="flex flex-wrap items-end gap-3 rounded-lg border p-4">
        <input type="hidden" name="bot_id" value={bot.id} />
        <label className="block space-y-2">Worker
          <select name="worker_id" required
            className="block h-10 min-w-52 rounded-md border bg-background px-3">
            {available.map(worker => <option key={worker.id} value={worker.id}>
              {worker.name} ({worker.slug})
            </option>)}
          </select>
        </label>
        <label className="block space-y-2">اولویت (کمتر = مقدم)
          <Input name="priority" type="number" min={1} max={1000}
            defaultValue={routes.items.length * 10 + 10} required />
        </label>
        <Button type="submit" variant="outline">افزودن مسیر غیرفعال</Button>
      </form> : null}
      {routes.items.length ? routes.items.map(route =>
        <RouteControls key={route.worker_id} bot={bot}
          route={route} enabled={workers.enabled} />) :
        <p className="rounded-lg border p-3 text-muted-foreground">
          برای این بات هنوز هیچ Worker ثبت نشده است.
        </p>}
      <p className="text-xs leading-7 text-muted-foreground">
        Rotation مرحله‌ای است: ابتدا کلید جدید را در Cloudflare provision کنید،
        سپس در این پنل Stage و با getMe تأیید کنید و بعد از حذف کلید قبلی در
        Cloudflare نسخهٔ Retiring را Revoke کنید. هیچ Secret در پاسخ‌ها برگردانده نمی‌شود.
      </p>
    </CardContent>
  </Card>;
}
