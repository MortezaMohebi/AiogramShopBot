"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { connectionReceipt, type ConnectionMutation } from "@/lib/mcp/connection-state";
import { mcpMutation } from "@/lib/mcp/client";

interface OwnedGrant {
  id: string; version: number; revoked: boolean; expires_at: string;
  gateway_issuer: string; client_id: string; connection_id: string;
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function receipt(value: unknown, id: string): value is OwnedGrant {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return row.id === id && Number.isSafeInteger(row.version) && (row.version as number) > 0 &&
    typeof row.revoked === "boolean" && typeof row.expires_at === "string" &&
    typeof row.gateway_issuer === "string" && typeof row.client_id === "string" && typeof row.connection_id === "string";
}

/** A validated account session can withdraw owned access after every Store is lost. */
export function McpWithdrawal({ initialId }: { initialId: string }) {
  const [id, setId] = useState(initialId);
  const [grant, setGrant] = useState<OwnedGrant | null>(null);
  const [mutation, setMutation] = useState<ConnectionMutation | null>(null);
  const [notice, setNotice] = useState("");
  const [reading, setReading] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const busy = useRef(false);
  const unresolved = mutation !== null && mutation.status !== "confirmed";

  async function inspect() {
    const selected = unresolved ? mutation!.request.id : id.trim().toLowerCase();
    if (!uuid.test(selected) || reading || busy.current) return;
    setReading(true);
    try {
      const response = await fetch("/api/admin/mcp/owned-grants/" + selected, { cache: "no-store" });
      const result: unknown = await response.json();
      if (!response.ok || !receipt(result, selected)) throw new Error("unconfirmed");
      setGrant(result);
      if (mutation && connectionReceipt(mutation.request, result)) {
        setMutation({ ...mutation, status: "confirmed" });setNotice("رسید لغو همین دسترسی دریافت شد.");
      } else setNotice(unresolved ? "لغو هنوز تأیید نشده است. درخواست تازه‌ای ارسال نشده است." : "وضعیت همین اتصال دریافت شد.");
    } catch { setNotice("وضعیت دریافت نشد یا این اتصال متعلق به حساب شما نیست. نتیجهٔ درخواست قبلی حفظ شده است."); }
    finally { setReading(false); }
  }

  async function revoke() {
    if (!grant || !confirmed || unresolved || busy.current || grant.revoked) return;
    busy.current = true;
    const request = { id: grant.id, action: "revoke" as const, expectedVersion: grant.version, storeIds: [], scopes: [] };
    setMutation({ request, status: "sending" });
    try {
      const response = await mcpMutation("/owned-grants/" + grant.id + "/revoke");
      const result: unknown = await response.json();
      if (!response.ok || !receipt(result, grant.id) || !connectionReceipt(request, result)) throw new Error("unconfirmed");
      setGrant(result);setMutation({ request, status: "confirmed" });setConfirmed(false);
      setNotice("دسترسی همین اتصال لغو شد. اثرهای ثبت‌شدهٔ قبلی برگردانده نمی‌شوند.");
    } catch {
      setMutation({ request, status: "unknown" });
      setNotice("پاسخ قطعی دریافت نشد. وضعیت همین شناسه را بخوانید؛ لغو دوباره‌ای خودکار ارسال نمی‌شود.");
    } finally { busy.current = false; }
  }

  return <section className="min-w-0 space-y-5 rounded-xl border border-border bg-card p-5 sm:p-7">
    <form className="space-y-3" onSubmit={(event) => { event.preventDefault();void inspect(); }}>
      <label className="block space-y-2"><span className="text-sm">شناسهٔ Grant در Native</span>
        <input className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" dir="ltr" value={id}
          onChange={(event) => { setId(event.target.value);setGrant(null);setConfirmed(false);setNotice("");setMutation(null); }} disabled={unresolved || reading}
          required maxLength={36} autoComplete="off" /></label>
      <Button variant="outline" type="submit" disabled={reading || mutation?.status === "sending" || !uuid.test(id)}>
        {reading ? "در حال دریافت…" : "بررسی وضعیت همین اتصال"}</Button>
    </form>
    {notice && <p role="status" aria-live="polite" className="text-sm leading-7">{notice}</p>}
    {grant && <div className="min-w-0 space-y-4">
      <dl className="space-y-3 text-sm">{[["Gateway", grant.gateway_issuer], ["Client", grant.client_id], ["Connection", grant.connection_id], ["Grant", grant.id]].map(([name, value]) =>
        <div key={name}><dt className="text-muted-foreground">{name}</dt><dd className="break-all"><bdi>{value}</bdi></dd></div>)}</dl>
      <p className="text-sm">وضعیت: <strong>{grant.revoked ? "لغوشده" : "لغو نشده"}</strong></p>
      {!grant.revoked && <div className="space-y-4 border-t pt-4">
        <p className="text-sm leading-7">این کار درخواست‌های تازهٔ این Grant را متوقف می‌کند. عملیات پذیرفته‌شده یا اثر ثبت‌شدهٔ قبلی برگردانده نمی‌شود.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmed} disabled={unresolved}
          onChange={(event) => setConfirmed(event.target.checked)} />لغو دسترسی همین اتصال را تأیید می‌کنم</label>
        <Button variant="destructive" disabled={!confirmed || unresolved} onClick={revoke}>لغو دسترسی همین اتصال</Button>
      </div>}
    </div>}
  </section>;
}
