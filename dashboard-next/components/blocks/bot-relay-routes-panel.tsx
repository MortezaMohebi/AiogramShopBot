import Link from "next/link";
import { PasswordActionForm } from "@/components/blocks/password-action-form";
import { assignRelayRoute } from "@/app/(console)/bots/[id]/relay-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import type { BotRecord } from "@/lib/bot-registry";
import { relayMessage, relayRouteLabel, type BotRelaySnapshot, type RelayWorkersSnapshot } from "@/lib/relay-pool";

export function BotRelayRoutesPanel({ bot, workers, routes, error, saved }: {
  bot: BotRecord; workers: RelayWorkersSnapshot; routes: BotRelaySnapshot; error?: string; saved?: string;
}) {
  if (bot.platform !== "telegram") return null;
  const assigned = new Set(routes.items.map(row => row.worker_id));
  const priorities = new Set(routes.items.map(row => row.priority));
  const nextPriority = Array.from({ length: 1000 }, (_, index) => index + 1)
    .find(value => value % 10 === 0 && !priorities.has(value)) ??
    Array.from({ length: 1000 }, (_, index) => index + 1).find(value => !priorities.has(value));
  const available = workers.items.filter(row => !assigned.has(row.id) && row.status !== "disabled");

  return <Card id="bot-relays" className="scroll-mt-24">
    <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
      <CardTitle>مسیرهای Relay ربات</CardTitle>
      <Button asChild variant="ghost" size="sm"><Link href="/relay-workers">مدیریت Workerها</Link></Button>
    </CardHeader>
    <CardContent className="space-y-3 text-sm">
      {!workers.enabled && <p>سرویس Relay متوقف است. <Link href="/services" className="text-primary underline">تنظیم سرویس</Link></p>}
      {error && <p role="alert" className="text-destructive">{relayMessage(error)}</p>}
      {saved === "removed" && <p role="status">مسیر از این ربات حذف شد.</p>}
      {routes.items.length ? <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-80 text-sm">
          <thead className="bg-muted"><tr>
            <th scope="col" className="p-2 text-start">Worker</th>
            <th scope="col" className="p-2 text-start">اولویت</th>
            <th scope="col" className="p-2 text-start">اتصال تلگرام</th>
          </tr></thead>
          <tbody>{routes.items.map(route => {
            const status = relayRouteLabel(route, workers.enabled);
            return <RecordClickArea as="tr" key={route.worker_id} className="border-t">
              <td className="p-2"><RecordLink href={`/bots/${bot.id}/relay/${route.worker_id}`}>{route.worker_name}</RecordLink></td>
              <td className="p-2">{route.priority.toLocaleString("fa-IR")}</td>
              <td className="p-2"><Badge tone={status === "متصل" ? "success" : "neutral"}>{status}</Badge></td>
            </RecordClickArea>;
          })}</tbody>
        </table>
      </div> : <p className="text-muted-foreground">هنوز مسیری برای این ربات ثبت نشده است.</p>}
      {available.length > 0 && <details>
        <summary className="w-fit cursor-pointer rounded-md px-1 font-medium text-primary hover:underline">افزودن مسیر</summary>
        <PasswordActionForm action={assignRelayRoute} when="required" includePassword={false} className="mt-3 flex flex-wrap items-end gap-3">
          <input type="hidden" name="bot_id" value={bot.id} />
          <label className="block space-y-2">Worker
            <select name="worker_id" required className="block h-10 max-w-full rounded-md border bg-background px-3">
              {available.map(worker => <option key={worker.id} value={worker.id}>{worker.name}</option>)}
            </select>
          </label>
          <label className="block space-y-2">اولویت
            <Input name="priority" type="number" min={1} max={1000} defaultValue={nextPriority} required className="w-24" />
          </label>
          <Button type="submit" size="sm">افزودن</Button>
        </PasswordActionForm>
      </details>}
    </CardContent>
  </Card>;
}
