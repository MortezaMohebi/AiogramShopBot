"use client";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { controlAction } from "@/lib/account-control";
export interface ConnectionData {
  active: Record<string, { mode: string; version: number; verified_at: string | null }>;
  items: { id: string; platform: string; previous_mode: string; requested_mode: string; state: string; error_code: string | null; created_at: string; updated_at: string; requested_by: number; approved_by: number | null }[];
}
const labels: Record<string, string> = { pending: "در انتظار تأیید", queued: "در صف اعمال", applying: "در حال بررسی و اعمال", succeeded: "تنظیم نزد Provider تأیید شد", failed: "ناموفق", cancelled: "لغوشده", needs_review: "نتیجه نامشخص؛ نیازمند بررسی" };
/** Show persisted operations; saving a request is never reported as activation. */
export function ConnectionControlPanel({ initial }: { initial: ConnectionData }) {
  const [data, setData] = useState(initial), [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const key = useRef<string | null>(null);
  const load = useCallback(async () => {
    const response = await fetch("/api/account/connections", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("خواندن وضعیت عملیات ممکن نشد.");
    const value = await response.json() as ConnectionData;
    if (!value.active || !Array.isArray(value.items)) throw new Error("پاسخ وضعیت معتبر نیست.");
    setData(value);
  }, []);
  const waiting = data.items.some((row) => row.state === "queued" || row.state === "applying");
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => { void load().catch(() => undefined); }, 3000);
    return () => clearInterval(timer);
  }, [waiting, load]);
  async function submit(event: FormEvent<HTMLFormElement>, operation?: string) {
    event.preventDefault(); if (busy) return;
    const form = event.currentTarget, fields = new FormData(form);
    setBusy(true); setNotice(null);
    try {
      if (operation) {
        await controlAction("connection-action", { operation_id: operation, action: fields.get("action"), current_password: fields.get("current_password"), second_factor: fields.get("second_factor") ?? "" });
      } else {
        key.current ??= crypto.randomUUID();
        await controlAction("connection-stage", { platform: fields.get("platform"), mode: fields.get("mode"), idempotency_key: key.current });
        key.current = null;
      }
      form.reset(); await load();
      setNotice({ ok: true, text: operation ? "درخواست ثبت شد؛ نتیجهٔ اعمال را در تاریخچه دنبال کنید." : "تغییر پیشنهادی ذخیره شد؛ هنوز روش دریافت پیام تغییر نکرده است." });
    } catch (error) { setNotice({ ok: false, text: error instanceof Error ? error.message : "عملیات انجام نشد." }); }
    finally { setBusy(false); }
  }
  return <div className="space-y-5" aria-busy={busy}>
    {notice ? <p role={notice.ok ? "status" : "alert"} className={notice.ok ? "rounded-lg bg-accent p-3 text-sm" : "rounded-lg bg-destructive/10 p-3 text-sm text-destructive"}>{notice.text}</p> : null}
    <div className="grid gap-4 md:grid-cols-2">{Object.entries(data.active).map(([platform, item]) => <Card key={platform}><CardHeader><CardTitle>{platform === "bale" ? "بله" : "تلگرام"}</CardTitle></CardHeader><CardContent className="space-y-2 text-sm"><p>روش ثبت‌شده: <b dir="ltr">{item.mode === "polling" ? "getUpdates" : "Webhook"}</b></p><p>نسخه تنظیمات: {item.version}</p><p className="text-xs text-muted-foreground">{item.verified_at ? `آخرین تأیید نزد Provider: ${new Date(item.verified_at).toLocaleString("fa-IR")}` : "این مقدار اولیه هنوز نزد Provider تأیید نشده است."}</p></CardContent></Card>)}</div>
    <Card><CardHeader><CardTitle>درخواست تغییر اتصال</CardTitle></CardHeader><CardContent>
      <form onSubmit={(event) => submit(event)} className="grid gap-4 md:grid-cols-3">
        <label className="space-y-2 text-sm">پیام‌رسان<select name="platform" className="h-10 w-full rounded-md border bg-background px-3" disabled={busy} onChange={() => { key.current = null; }}><option value="telegram">تلگرام</option><option value="bale">بله</option></select></label>
        <label className="space-y-2 text-sm">روش موردنظر<select name="mode" className="h-10 w-full rounded-md border bg-background px-3" disabled={busy} onChange={() => { key.current = null; }}><option value="webhook">Webhook</option><option value="polling">getUpdates — Long Polling</option></select></label>
        <div className="flex items-end"><Button type="submit" disabled={busy}>ثبت پیشنهاد تغییر</Button></div>
      </form>
      <p className="mt-4 text-xs leading-7 text-muted-foreground">اعمال از داخل پنل، پس از تأیید رمز و MFA انجام می‌شود. پیام‌های منتظر حذف نمی‌شوند. نشانی Webhook فقط از تنظیمات امن سرور خوانده می‌شود؛ دریافت پیام واقعی را پس از اعمال جداگانه آزمایش کنید.</p>
    </CardContent></Card>
    <div className="flex items-center justify-between gap-3"><h2 className="font-semibold">تاریخچه و نتیجهٔ اعمال</h2><Button type="button" variant="outline" disabled={busy} onClick={() => void load().catch(() => setNotice({ ok: false, text: "خواندن وضعیت ممکن نشد." }))}>تازه‌سازی وضعیت</Button></div>
    {data.items.map((row) => <Card key={row.id}><CardContent className="space-y-3 py-5">
      <div className="flex flex-wrap justify-between gap-2 text-sm"><strong>{row.platform === "bale" ? "بله" : "تلگرام"} · {row.previous_mode} ← {row.requested_mode}</strong><span>{labels[row.state] ?? row.state}</span></div>
      <p dir="ltr" className="break-all text-xs text-muted-foreground">{row.id}</p>
      <p className="text-xs text-muted-foreground">درخواست‌دهنده #{row.requested_by}{row.approved_by ? ` · تأییدکننده #${row.approved_by}` : ""} · {new Date(row.updated_at).toLocaleString("fa-IR")}</p>
      {row.error_code ? <p role="alert" className="text-xs text-destructive">نتیجه نیازمند بررسی است؛ ثبت مجدد خودکار انجام نمی‌شود. کد پیگیری: <span dir="ltr">{row.error_code}</span></p> : null}
      {["pending", "queued", "needs_review"].includes(row.state) ? <details><summary className="cursor-pointer text-sm font-medium">تأیید عملیات</summary><form onSubmit={(event) => submit(event, row.id)} className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="space-y-1 text-xs">رمز فعلی<Input name="current_password" type="password" autoComplete="current-password" required maxLength={256} dir="ltr" disabled={busy} /></label>
        <label className="space-y-1 text-xs">کد MFA یا بازیابی (اگر فعال است)<Input name="second_factor" autoComplete="one-time-code" maxLength={64} dir="ltr" disabled={busy} /></label>
        <label className="space-y-1 text-xs">عملیات<select name="action" className="h-10 w-full rounded-md border bg-background px-3" disabled={busy}>{row.state === "needs_review" ? <option value="reconcile">بررسی نتیجه نزد Provider بدون تکرار تغییر</option> : <>{row.state === "pending" ? <option value="apply">تأیید و اعمال تغییر</option> : null}<option value="cancel">لغو درخواست</option></>}</select></label>
        <div className="flex items-end"><Button type="submit" disabled={busy}>تأیید با هویت من</Button></div>
      </form></details> : null}
    </CardContent></Card>)}
    {!data.items.length ? <p className="py-5 text-center text-sm text-muted-foreground">هنوز تغییری ثبت نشده است.</p> : null}
  </div>;
}
