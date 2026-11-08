"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { connectionReceipt, gatewayDashboardUrl, reconcileConnection, type ConnectionMutation, type ConnectionRequest } from "@/lib/mcp/connection-state";
import type { McpGrantView, McpHistoryPage, McpPage, McpPairingView } from "@/lib/mcp/types";
import { mcpMutation } from "@/lib/mcp/client";

const stamp = (value: string) => new Intl.DateTimeFormat("fa-IR", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran",
}).format(new Date(value));
const historyLabels: Record<string, string> = {
  pending: "نتیجهٔ نامعلوم", succeeded: "رسید درخواست ثبت شد",
  awaiting_gateway: "در انتظار تصمیم در WPMCP", cancelled: "لغو شد",
};
const panel = "min-w-0 space-y-4 rounded-xl border border-border bg-card p-5";
const technical = "break-all rounded bg-muted/60 px-2 py-1 font-mono text-xs";

/** Human delegation consent is separate from every business approval in WPMCP. */
export function McpConnections({ initial, history, pairing: initialPairing, pairingError }: {
  initial: McpPage;
  history: McpHistoryPage;
  pairing: McpPairingView | null;
  pairingError: boolean;
}) {
  const [data, setData] = useState(initial);
  const [pairing, setPairing] = useState(initialPairing);
  const [mutation, setMutation] = useState<ConnectionMutation | null>(null);
  const [withdraw, setWithdraw] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [reading, setReading] = useState(false);
  const mounted = useRef(true);
  const sending = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const unsettled = mutation !== null && mutation.status !== "confirmed";

  /** Refresh changes inventory; it cannot erase an unresolved mutation. */
  async function refresh() {
    if (reading || sending.current) return;
    setReading(true);
    try {
      if (mutation && mutation.status !== "confirmed") {
        const family = mutation.request.action === "revoke" ? "owned-grants" : "grants";
        const response = await fetch(`/api/admin/mcp/${family}/${mutation.request.id}`, { cache: "no-store" });
        const receipt: unknown = response.ok ? await response.json() : null;
        if (mounted.current) {
          const next = reconcileConnection(mutation, receipt);
          setMutation(next);
          setNotice(next.status === "confirmed" ? "رسید همین درخواست دریافت شد." : "نتیجه هنوز قطعی نیست. درخواست تازه‌ای ارسال نشده است.");
        }
      }
      const response = await fetch(`/api/admin/mcp?page=${data.page}`, { cache: "no-store" });
      if (!response.ok) throw new Error("unavailable");
      const updated: McpPage = await response.json();
      if (updated.store_id !== initial.store_id || !Array.isArray(updated.items)) throw new Error("scope_changed");
      if (mounted.current) setData(updated);
    } catch {
      if (mounted.current) setNotice("وضعیت دریافت نشد. نتیجهٔ درخواست قبلی همچنان حفظ شده است.");
    } finally { if (mounted.current) setReading(false); }
  }

  async function change(request: ConnectionRequest) {
    if (sending.current || unsettled) return;
    sending.current = true;
    setMutation({ request, status: "sending" });
    setNotice("");
    const target = request.action === "confirm"
      ? `/pairings/${request.id}/confirm` : `/owned-grants/${request.id}/revoke`;
    try {
      const response = await mcpMutation(target);
      const result: unknown = await response.json();
      if (!response.ok || !connectionReceipt(request, result)) throw new Error("unconfirmed");
      if (!mounted.current) return;
      setMutation({ request, status: "confirmed" });
      if (request.action === "confirm") setPairing((current) => current?.id === request.id
        ? { ...current, confirmed: true, can_confirm: false } : current);
      setWithdraw(null);
      setNotice(request.action === "confirm" ? "دسترسی همین اتصال ثبت شد. ادامهٔ اتصال را در WPMCP بررسی کنید."
        : "دسترسی همین اتصال لغو شد. این کار اثرهای ثبت‌شدهٔ قبلی را برنمی‌گرداند.");
      if (request.action === "revoke") setData((current) => ({ ...current,
        items: current.items.map((item) => item.id === request.id
          ? { ...item, revoked: true, can_revoke: false, version: (result as McpGrantView).version } : item),
      }));
    } catch {
      if (mounted.current) {
        setMutation({ request, status: "unknown" });
        setNotice("پاسخ قطعی دریافت نشد. ابتدا وضعیت همین شناسه را بررسی کنید؛ درخواست تازه‌ای نفرستید. اگر احراز هویت تازه لازم است، به حساب کاربری بروید.");
      }
    } finally { sending.current = false; }
  }

  return <div className="min-w-0 space-y-6">
    <section className={panel} aria-label="دسترسی اتصال‌های MCP">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold">اتصال‌های شما در فروشگاه انتخاب‌شده</h2>
        <Button variant="outline" onClick={refresh} disabled={reading || mutation?.status === "sending"}>
          {reading ? "در حال دریافت…" : "بررسی وضعیت"}
        </Button>
      </div>
      <p className="text-sm leading-7 text-muted-foreground">این صفحه فقط دسترسی اتصال را مدیریت می‌کند. تصمیم انسانی دربارهٔ انتشار، تغییر حساس یا کنترل اجرا در WPMCP ثبت می‌شود.</p>
      <p className="text-sm">وضعیت سرویس MCP: <strong>{data.enabled ? "فعال" : "غیرفعال"}</strong></p>
      <p className="text-sm">شناسهٔ فروشگاه: <bdi className={technical}>{data.store_id}</bdi></p>
      {notice && <p role="status" aria-live="polite" className="rounded-lg border border-border bg-muted/40 p-3 text-sm leading-7">{notice}</p>}
      {mutation?.status === "unknown" && <p className="text-sm">شناسهٔ درخواست: <bdi className={technical}>{mutation.request.id}</bdi> · <Link className="underline" href="/account">حساب کاربری</Link></p>}
    </section>

    {pairingError && <div role="alert" className={panel}>درخواست اتصال در دسترس نیست، منقضی شده یا دسترسی مدیریت همهٔ فروشگاه‌های آن را ندارید.</div>}
    {pairing && <section className={panel} aria-labelledby="pairing-title">
      <h2 id="pairing-title" className="text-lg font-semibold">بررسی دسترسی اتصال</h2>
      <p className="text-sm leading-7 text-muted-foreground">هویت WPMCP، فروشگاه‌ها و دسترسی‌های درخواستی را بررسی کنید. ثبت این دسترسی به معنی تأیید انتشار یا اجرای عملیات تجاری نیست.</p>
      <dl className="grid min-w-0 gap-3 text-sm sm:grid-cols-[minmax(8rem,1fr)_minmax(0,3fr)]">
        {[["درگاه (Gateway)", pairing.identity.iss], ["برنامه (Client)", pairing.identity.client_id], ["درخواست‌دهنده", pairing.identity.sub],
          ["فضای کاری (Workspace)", pairing.identity.workspace_id], ["حساب (Tenant)", pairing.identity.tenant_id], ["اتصال", pairing.identity.connection_id],
          ["شناسهٔ دسترسی (Grant)", pairing.id]].map(([label, value]) => <div className="contents" key={label}>
            <dt className="text-muted-foreground">{label}</dt><dd className="min-w-0 break-all"><bdi>{value}</bdi></dd>
          </div>)}
      </dl>
      <div><h3 className="mb-2 text-sm font-semibold">فروشگاه‌های درخواستی</h3><ul className="space-y-2">{pairing.store_ids.map((id) => <li key={id}><bdi className={technical}>{id}</bdi></li>)}</ul></div>
      <div><h3 className="mb-2 text-sm font-semibold">دسترسی‌های درخواستی</h3><ul className="flex flex-wrap gap-2">{pairing.scopes.map((scope) => <li key={scope}><bdi className={technical}>{scope}</bdi></li>)}</ul></div>
      <p className="text-sm text-muted-foreground">مهلت تأیید: {stamp(pairing.expires_at)} به وقت تهران. برای تغییر فروشگاه یا دسترسی‌ها، درخواست تازه‌ای در WPMCP بسازید.</p>
      {pairing.confirmed || mutation?.status === "confirmed" && mutation.request.action === "confirm"
        ? <p role="status">دسترسی این اتصال قبلاً ثبت شده است.</p>
        : <Button disabled={!data.enabled || !pairing.can_confirm || unsettled} onClick={() => change({
          id: pairing.id, action: "confirm", expectedVersion: 0, storeIds: pairing.store_ids, scopes: pairing.scopes,
        })}>ثبت دسترسی این اتصال</Button>}
      {!pairing.can_confirm && !pairing.confirmed && <p className="text-sm text-muted-foreground">ثبت دسترسی با هویت و مجوز فعلی در دسترس نیست.</p>}
    </section>}

    <section className="min-w-0 space-y-3" aria-label="فهرست اتصال‌ها">
      {!data.items.length && <p className={panel}>برای این فروشگاه هنوز اتصالی متعلق به شما ثبت نشده است. درخواست اتصال را از WPMCP شروع کنید.</p>}
      {data.items.map((grant) => {
        const gateway = gatewayDashboardUrl(grant.gateway.issuer, grant.gateway.workspace_id);
        return <article className={panel} key={grant.id}>
          <div className="flex flex-wrap items-start justify-between gap-3"><h2 className="min-w-0 break-all font-semibold"><bdi>{grant.gateway.client_id}</bdi></h2>
            <span className="rounded-md border px-2 py-1 text-xs">{grant.revoked ? "لغوشده" : grant.expired ? "منقضی" : "دارای دسترسی"}</span></div>
          <p className="break-all text-sm text-muted-foreground"><bdi>{grant.gateway.issuer}</bdi></p>
          <p className="text-sm">شناسهٔ دسترسی: <bdi className={technical}>{grant.id}</bdi></p>
          <ul className="flex flex-wrap gap-2" aria-label="دسترسی‌های اتصال">{grant.scopes.map((scope) => <li key={scope}><bdi className={technical}>{scope}</bdi></li>)}</ul>
          <p className="text-sm text-muted-foreground">انقضای دسترسی: {stamp(grant.expires_at)} به وقت تهران</p>
          <div className="flex flex-wrap gap-3">{gateway && <Button asChild variant="outline"><a href={gateway} target="_blank" rel="noopener noreferrer">بررسی در WPMCP</a></Button>}
            {grant.can_revoke && <Button variant="outline" disabled={unsettled} onClick={() => setWithdraw(grant.id)}>لغو دسترسی</Button>}</div>
          {withdraw === grant.id && <div className="space-y-3 rounded-lg border border-destructive/40 p-4" role="group" aria-label="تأیید لغو دسترسی">
            <p className="text-sm leading-7">درخواست‌های تازهٔ این اتصال متوقف می‌شوند. اثر ثبت‌شده یا عملیات پذیرفته‌شدهٔ قبلی برگردانده نمی‌شود.</p>
            <div className="flex flex-wrap gap-3"><Button variant="destructive" disabled={unsettled} onClick={() => change({
              id: grant.id, action: "revoke", expectedVersion: grant.version, storeIds: grant.store_ids, scopes: grant.scopes,
            })}>لغو دسترسی همین اتصال</Button><Button variant="ghost" disabled={unsettled} onClick={() => setWithdraw(null)}>انصراف</Button></div>
          </div>}
        </article>;
      })}
      {!unsettled && <div className="flex flex-wrap gap-3">{data.page > 1 && <Link className="underline" href={`/studio/mcp?page=${data.page - 1}`}>صفحهٔ قبل</Link>}
        {data.has_more && <Link className="underline" href={`/studio/mcp?page=${data.page + 1}`}>صفحهٔ بعد</Link>}</div>}
    </section>

    <section className={panel} aria-label="رسیدهای درخواست‌های MCP">
      <h2 className="font-semibold">آخرین رسیدهای درخواست‌های MCP</h2>
      <p className="text-sm text-muted-foreground">این رسیدها نتیجهٔ تصمیم یا اجرای WPMCP را تأیید نمی‌کنند. وضعیت آن‌ها را در WPMCP بررسی کنید.</p>
      {!history.items.length ? <p className="text-sm">هنوز رسیدی برای شما در این فروشگاه ثبت نشده است.</p>
        : <ul className="space-y-4">{history.items.map((item) => <li className="min-w-0 border-t pt-3 text-sm" key={item.operation_id}>
          <div className="flex flex-wrap justify-between gap-2"><bdi>{item.tool}</bdi><span>{historyLabels[item.state] ?? "وضعیت در دسترس نیست"}</span></div>
          <bdi className="mt-2 block break-all font-mono text-xs">{item.operation_id}</bdi>
        </li>)}</ul>}
      {!unsettled && <div className="flex flex-wrap gap-3">{history.page > 1 && <Link className="underline" href={`/studio/mcp?page=${data.page}&history_page=${history.page - 1}`}>رسیدهای جدیدتر</Link>}
        {history.has_more && <Link className="underline" href={`/studio/mcp?page=${data.page}&history_page=${history.page + 1}`}>رسیدهای قدیمی‌تر</Link>}</div>}
    </section>
  </div>;
}
