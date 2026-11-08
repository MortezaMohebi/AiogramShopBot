import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { BotRegistryDetail } from "@/lib/bot-registry";

const states = { active: "فعال", maintenance: "نگهداری", paused: "متوقف", disabled: "غیرفعال" };
const actions: Record<string, string> = {
  bot_drafted: "ساخت پیش‌نویس",
  bot_updated: "به‌روزرسانی ربات",
  credential_staged: "ثبت توکن",
  credential_revoked: "لغو توکن",
};
const count = new Intl.NumberFormat("fa-IR");

export function BotChangeHistory({ events, state_events }: Pick<
  BotRegistryDetail, "events" | "state_events"
>) {
  const entries = [
    ...state_events.map(entry => ({
      key: `state-${entry.id}`,
      title: `تغییر وضعیت از «${states[entry.previous_state]}» به «${states[entry.next_state]}»`,
      actor: entry.actor_id,
      time: entry.created_at,
      note: entry.reason,
    })),
    ...events.map(entry => ({
      key: `event-${entry.id}`,
      title: actions[entry.action] ?? entry.action,
      actor: entry.actor_id,
      time: entry.created_at,
      note: entry.credential_version === null ? null : `نسخهٔ توکن ${count.format(entry.credential_version)}`,
    })),
  ].sort((a, b) => (Date.parse(b.time ?? "") || 0) - (Date.parse(a.time ?? "") || 0));

  return <Card>
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-3 rounded-xl px-4 py-3 focus-visible:outline focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <h2 className="min-w-0 flex-1 text-sm font-semibold">تاریخچهٔ تغییرات ربات</h2>
        <span className="text-xs text-muted-foreground">{count.format(entries.length)} رویداد</span>
        <ChevronDown aria-hidden="true" className="size-4 shrink-0 group-open:rotate-180" />
      </summary>
      {entries.length ? <ul className="max-h-64 divide-y overflow-auto border-t px-4"
        tabIndex={0} aria-label="رویدادهای ربات">
        {entries.map(entry => <li key={entry.key} className="py-2 text-xs">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="font-medium">{entry.title}</span>
            <span className="text-muted-foreground">
              {entry.actor === null ? "سیستم" : `مدیر ${count.format(entry.actor)}`}
              {entry.time ? <> · <time dateTime={entry.time}>{new Date(entry.time).toLocaleString("fa-IR")}</time></> : null}
            </span>
          </div>
          {entry.note ? <p className="mt-1 break-words text-muted-foreground">{entry.note}</p> : null}
        </li>)}
      </ul> : <p className="border-t px-4 py-3 text-xs text-muted-foreground">هنوز رویدادی ثبت نشده است.</p>}
    </details>
  </Card>;
}
