"use client";

import { type FormEvent, useState } from "react";
import { CheckCircle2, Copy, RefreshCw, TriangleAlert } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import type {
  BotConnections,
  BotProviderProbe,
} from "@/lib/bot-connections";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface ProbeResult {
  ok: boolean;
  probe?: BotProviderProbe;
  code?: string;
}

interface ModeResult {
  ok: boolean;
  pending_update_mode?: string;
  code?: string;
}

/** UI never receives Bot API tokens or Bale's secret webhook path. */
export function BotConnectionsPanel({
  initial,
}: {
  initial: BotConnections;
}) {
  const [probe, setProbe] = useState<BotProviderProbe | null>(null);
  const [probing, setProbing] = useState(false);
  const [stageMode, setStageMode] = useState<"webhook" | "polling">(
    initial.telegram.update_mode,
  );
  const [pending, setPending] = useState<string | null>(
    initial.telegram.pending_update_mode,
  );
  const [staging, setStaging] = useState(false);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);

  async function refresh() {
    setProbing(true);
    setFeedback(null);
    try {
      const response = await fetch("/api/admin/bot-connections", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal: AbortSignal.timeout(25_000),
      });
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
        throw new Error("not-json");
      }
      const result = (await response.json()) as ProbeResult;
      if (!response.ok || !result.ok || !result.probe) {
        throw new Error(result.code ?? "unknown");
      }
      setProbe(result.probe);
    } catch {
      setFeedback({
        ok: false,
        message: "بررسی اتصال انجام نشد. وضعیت سرور و اتصال اینترنت را بررسی کنید.",
      });
    } finally {
      setProbing(false);
    }
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setFeedback({ ok: true, message: "آدرس Webhook کپی شد." });
    } catch {
      setFeedback({ ok: false, message: "کپی انجام نشد؛ آدرس را دستی انتخاب کنید." });
    }
  }

  async function stage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (staging) return;
    setStaging(true);
    setFeedback(null);
    try {
      const csrf = await requestBrowserChallenge();
      const response = await fetch(
        "/api/admin/bot-connections/mode-request",
        {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          redirect: "error",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-Shop-Login-Challenge": csrf,
          },
          body: JSON.stringify({
            mode: stageMode,
            confirmation: "STAGE_TELEGRAM_MODE",
          }),
          signal: AbortSignal.timeout(20_000),
        },
      );
      const result = (await response.json()) as ModeResult;
      if (!response.ok || !result.ok) {
        throw new Error(result.code ?? "unknown");
      }
      setPending(result.pending_update_mode ?? stageMode);
      setFeedback({
        ok: true,
        message:
          "درخواست تغییر ثبت شد. روش دریافت هنوز تغییر نکرده است؛ "
          + "برای فعال‌سازی، دستور apply-bot-mode را در Codespace اجرا کنید.",
      });
    } catch {
      setFeedback({
        ok: false,
        message: "درخواست ثبت نشد. دسترسی حساب و اتصال را بررسی کنید.",
      });
    } finally {
      setStaging(false);
    }
  }

  const telegram = probe?.telegram;
  const bale = probe?.bale;

  return (
    <div className="space-y-6">
      {feedback ? (
        <div
          role={feedback.ok ? "status" : "alert"}
          className={feedback.ok
            ? "flex gap-2 rounded-lg bg-accent p-3 text-sm text-accent-foreground"
            : "flex gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"}
        >
          {feedback.ok
            ? <CheckCircle2 aria-hidden="true" className="size-4 shrink-0" />
            : <TriangleAlert aria-hidden="true" className="size-4 shrink-0" />}
          {feedback.message}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>تلگرام</CardTitle>
            <CardDescription>
              شیوهٔ دریافت پیام و اتصال به Telegram Bot API
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <p>ربات پیکربندی شده: <strong>{initial.telegram.configured ? "بله" : "خیر"}</strong></p>
            <p>
              روش فعال دریافت: <strong dir="ltr">
                {initial.telegram.update_mode === "polling"
                  ? "getUpdates (long polling)"
                  : "Webhook"}
              </strong>
            </p>
            <p>
              مسیر اتصال API: <strong dir="ltr">{initial.telegram.api_transport}</strong>
            </p>
            <p className="text-xs text-muted-foreground">
              Cloudflare Worker: {initial.telegram.worker_configured ? "تنظیم شده" : "تنظیم نشده"}
              {" · "}
              HTTP Proxy: {initial.telegram.proxy_configured ? "تنظیم شده" : "تنظیم نشده"}
            </p>
            {initial.telegram.webhook_url ? (
              <div className="space-y-2">
                <p className="font-medium">آدرس فعالِ پیکربندی‌شده Webhook</p>
                <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted p-3">
                  <code dir="ltr" className="min-w-0 flex-1 break-all text-xs">
                    {initial.telegram.webhook_url}
                  </code>
                  <Button
                    type="button" size="sm" variant="outline"
                    onClick={() => copy(initial.telegram.webhook_url!)}
                  >
                    <Copy aria-hidden="true" className="size-4" /> کپی
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                در getUpdates، Webhook نباید ثبت شده باشد.
              </p>
            )}
            {telegram ? (
              <div role="status" className="rounded-lg border p-3 text-xs leading-7">
                <p>اتصال واقعی: <strong>{telegram.status === "connected" ? "برقرار" : "در دسترس نیست"}</strong></p>
                {telegram.username ? <p>نام ربات: <span dir="ltr">@{telegram.username}</span></p> : null}
                {telegram.provider_mode ? <p>روش ثبت‌شده نزد Telegram: {telegram.provider_mode}</p> : null}
                {typeof telegram.pending_updates === "number" ? <p>پیام‌های در انتظار: {telegram.pending_updates}</p> : null}
                {typeof telegram.webhook_matches === "boolean" ? (
                  <p>همخوانی با تنظیم فعلی: {telegram.webhook_matches ? "بله" : "خیر"}</p>
                ) : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>بله</CardTitle>
            <CardDescription>
              وب‌هوک بازوی بله و اتصال مستقل به Bale Bot API
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <p>بازو پیکربندی شده: <strong>{initial.bale.configured ? "بله" : "خیر"}</strong></p>
            <p>روش دریافت: <strong dir="ltr">Webhook</strong></p>
            <p className="text-xs text-muted-foreground">
              برای بله فقط دریافت با Webhook در دسترس است.
            </p>
            {initial.bale.webhook_url_label ? (
              <div className="space-y-2">
                <p className="font-medium">مسیر Webhook بله (Secret مخفی)</p>
                <code dir="ltr" className="block break-all rounded-lg bg-muted p-3 text-xs">
                  {initial.bale.webhook_url_label}
                </code>
              </div>
            ) : null}
            {bale ? (
              <div role="status" className="rounded-lg border p-3 text-xs leading-7">
                <p>اتصال واقعی: <strong>{bale.status === "connected" ? "برقرار" : "در دسترس نیست"}</strong></p>
                {bale.username ? <p>نام بازو: <span dir="ltr">@{bale.username}</span></p> : null}
                {bale.webhook_status ? <p>وضعیت Webhook: {bale.webhook_status}</p> : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Button type="button" variant="outline" onClick={refresh} disabled={probing}>
        <RefreshCw aria-hidden="true" className={probing ? "size-4 animate-spin" : "size-4"} />
        {probing ? "در حال بررسی Telegram و Bale..." : "بررسی اتصال تلگرام و بله"}
      </Button>

      <Card>
        <CardHeader>
          <CardTitle>روش دریافت پیام‌های Telegram</CardTitle>
          <CardDescription>
            اعمال تغییر به راه‌اندازی مجدد سرویس دریافت پیام نیاز دارد. ثبت درخواست، اتصال فعلی را تغییر نمی‌دهد.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={stage} className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <label className="block min-w-0 flex-1 space-y-2 text-sm">
              روش موردنظر
              <select
                value={stageMode}
                onChange={(event) => setStageMode(
                  event.target.value as "webhook" | "polling",
                )}
                className="h-10 w-full rounded-md border border-input bg-background px-3"
              >
                <option value="webhook">Webhook — دریافت HTTP از Telegram</option>
                <option value="polling">getUpdates — Long Polling</option>
              </select>
            </label>
            <Button type="submit" disabled={staging}>
              {staging ? "در حال ثبت..." : "ثبت درخواست تغییر حالت"}
            </Button>
          </form>
          {pending ? (
            <p role="status" className="text-sm text-muted-foreground">
              تغییر در انتظار فعال‌سازی: <strong dir="ltr">{pending}</strong>
            </p>
          ) : null}
          <p className="text-xs leading-7 text-muted-foreground">
            برای اعمال تنظیم در محیط Codespaces، بعد از ثبت درخواست
            در ترمینال خصوصی اجرا کنید:
          </p>
          <code dir="ltr" className="block overflow-x-auto rounded-lg bg-muted p-3 text-xs">
            bash scripts/setup_codespace.sh apply-bot-mode
          </code>
          <p className="text-xs leading-6 text-muted-foreground">
            برای برگشت به Webhook، ثبت Provider نیز با دستور connect و تأیید جداگانه انجام می‌شود.
            برای کاهش ریسک پیام‌های ازدست‌رفته، هیچ دستور drop_pending_updates استفاده نمی‌شود.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
