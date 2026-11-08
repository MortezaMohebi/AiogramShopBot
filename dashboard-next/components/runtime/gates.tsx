"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RuntimeMutationNotice, useRuntimeMutation } from "./use-mutation";
import { RuntimeId, RuntimePanel } from "./shared";
import { gateStatus, gateLabels } from "@/lib/runtime/state";
import type { RuntimeGate, RuntimeOverview } from "@/lib/runtime/types";
import type { BotChoice } from "@/lib/workflows/types";
function GateRow({
  gate,
  title,
  canManage
}: {
  gate: RuntimeGate;
  title: string;
  canManage: boolean;
}) {
  const [enabled, setEnabled] = useState(gate.enabled),
    [killed, setKilled] = useState(gate.killed),
    [approved, setApproved] = useState(false);
  const mutation = useRuntimeMutation(),
    dirty = enabled !== gate.enabled || killed !== gate.killed;
  return <div className="min-w-0 space-y-3 rounded-lg border p-4">
  <div className="flex flex-wrap items-center justify-between gap-3">
    <h3 className="text-sm font-semibold">
      {title}
    </h3>
    <Badge tone={gate.killed ? "danger" : gate.enabled ? "success" : "neutral"}>
      {gate.killed ? "توقف اضطراری" : gate.enabled ? "مجاز" : "غیرفعال"}
    </Badge>
  </div>
  {gate.bot_id && <RuntimeId>
    {gate.bot_id}
  </RuntimeId>}
  <p className="text-xs text-muted-foreground">نسخهٔ تنظیم: {gate.version.toLocaleString("fa-IR")}</p>
  {canManage && <form className="space-y-3" onSubmit={e => {
      e.preventDefault();
      const operationId = crypto.randomUUID();
      void mutation.execute("/gates", {
        bot_id: gate.bot_id,
        expected_version: gate.version,
        enabled,
        killed,
        operation_id: operationId
      }, "تنظیم اجرا ثبت شد.", {
        operationId,
        scopeKey: gate.scope_key
      });
    }}>
    <fieldset disabled={mutation.disabled} className="space-y-3 disabled:opacity-60">
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={enabled} onChange={e => {
            setEnabled(e.target.checked);
            setApproved(false);
          }} className="mt-1" />مجوز اجرای فرایند</label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={killed} onChange={e => {
            setKilled(e.target.checked);
            setApproved(false);
          }} className="mt-1" />توقف اضطراری و بازگشت به مسیر قبلی ربات</label>
      {dirty && <label className="flex items-start gap-2 text-xs leading-6"><input type="checkbox" checked={approved} onChange={e => setApproved(e.target.checked)} className="mt-1" />تغییر مجوز همین محدوده را تأیید می‌کنم.</label>}
      <Button type="submit" size="sm" variant={killed ? "destructive" : "outline"} disabled={!dirty || !approved}>ذخیرهٔ تنظیم اجرا</Button>
    </fieldset>
  </form>}
  <RuntimeMutationNotice mutation={mutation} />
</div>;
}
/** Absent persistent gates display the server's default-off state with CAS version zero. */
export function RuntimeGates({
  overview,
  bots,
  storeId
}: {
  overview: RuntimeOverview;
  bots: BotChoice[];
  storeId: string;
}) {
  const store = overview.gates.find(g => g.bot_id === null) ?? {
    scope_key: `store:${storeId}`,
    bot_id: null,
    enabled: false,
    killed: false,
    version: 0
  };
  const botMap = new Map(bots.map(bot => [bot.id, bot.name]));
  const ids = [...new Set([...bots.map(bot => bot.id), ...overview.gates.flatMap(g => g.bot_id ? [g.bot_id] : [])])];
  return <RuntimePanel title="مجوز اجرا و توقف اضطراری">
  <p className="text-sm leading-7">{gateLabels[gateStatus(overview)]}. انتشار به‌تنهایی مجوز فروشگاه یا ربات را فعال نمی‌کند.</p>
  {!overview.can_manage && <p className="text-xs text-muted-foreground">دسترسی این حساب برای مشاهده است؛ تغییر مجوز اجرا به مدیر فروشگاه نیاز دارد.</p>}
  <div className="grid min-w-0 gap-4 md:grid-cols-2">
    <GateRow key={`store-${store.version}`} gate={store} title="فروشگاه جاری" canManage={overview.can_manage} />
    {ids.map(id => {
        const gate = overview.gates.find(g => g.bot_id === id) ?? {
          scope_key: `bot:${id}`,
          bot_id: id,
          enabled: false,
          killed: false,
          version: 0
        };
        return <div key={`${id}-${gate.version}`} className="min-w-0 space-y-2">
      <GateRow gate={gate} title={botMap.get(id) ?? "ربات"} canManage={overview.can_manage} />
      <p className="px-2 text-xs leading-6 text-muted-foreground">
        {gateLabels[gateStatus(overview, id)]}
      </p>
    </div>;
      })}
  </div>
</RuntimePanel>;
}
