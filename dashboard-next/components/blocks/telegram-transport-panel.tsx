"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  CheckCircle2, CircleHelp, Cloud, LockKeyhole, Network, RefreshCcw,
  RotateCcw, ShieldAlert, ShieldCheck, TestTube2, Wifi,
} from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Mode = "direct" | "http_proxy" | "cloudflare_worker";
type State =
  | "pending" | "applying" | "succeeded"
  | "failed" | "cancelled" | "needs_review";

export interface TelegramTransportActive {
  mode: Mode;
  label: string;
  version: number;
  source: "database" | "deployment";
  proxy_url: string;
  proxy_username: string;
  has_proxy_password: boolean;
  worker_url: string;
  has_worker_secret: boolean;
  verified_at: string | null;
  verified_bot_id: string | null;
}
interface TransportSummary {
  mode: Mode;
  label: string;
  proxy_url: string;
  worker_url: string;
}
export interface TelegramTransportHistory {
  id: string;
  operation: "switch" | "rollback";
  status: State;
  proposed: TransportSummary;
  expected_version: number;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}
export interface TelegramTransportData {
  active: TelegramTransportActive;
  approved_proxy_urls: string[];
  approved_worker_origins: string[];
  history: TelegramTransportHistory[];
}
type Result = {
  ok?: boolean;
  code?: string;
  requestId?: string;
  status?: string;
  applied?: boolean;
  verified_bot_id?: string;
  round_trip_ms?: number;
};

const errorText: Record<string, string> = {
  invalid_request: "مشخصات درخواست یا فیلدهای انتخابی معتبر نیستند.",
  invalid_transport_mode: "نوع اتصال انتخاب‌شده پشتیبانی نمی‌شود.",
  invalid_proxy_endpoint: "آدرس Proxy نامعتبر است؛ باید HTTP یا SOCKS5 با پورت مشخص باشد.",
  transport_endpoint_not_approved: "این آدرس هنوز در Allowlist امن Deployment تأیید نشده است.",
  invalid_proxy_credentials: "نام کاربری و رمز Proxy باید باهم و بدون نویسه‌های کنترلی وارد شوند.",
  invalid_worker_origin: "آدرس Worker باید HTTPS Origin معتبر و بدون مسیر یا Query باشد.",
  invalid_worker_secret: "Relay Key حداقل ۳۲ نویسه لازم دارد؛ کلید را در فرم وارد کنید.",
  mfa_enrollment_required: "ابتدا احراز هویت دومرحله‌ای حساب مدیر را فعال کنید.",
  mfa_required: "کد MFA یا بازیابی معتبر را وارد کنید.",
  invalid_verification: "کد MFA معتبر نیست یا قبلاً مصرف شده است.",
  invalid_credentials: "رمز فعلی حساب درست نیست.",
  reauthentication_required: "برای انجام این تغییر، هویت خود را در «حساب من» دوباره تأیید کنید.",
  temporarily_locked: "تلاش‌های امنیتی بیش‌ازحد شده‌اند؛ بعداً وضعیت را بررسی کنید.",
  transport_stage_expired: "اعتبار پیشنهاد به پایان رسیده؛ باید پیشنهاد جدید ثبت شود.",
  transport_unchanged: "این تنظیمات با مسیر فعال یکسان هستند.",
  bot_identity_mismatch: "شناسهٔ واقعی بات با شناسهٔ تأییدشده متفاوت است؛ هیچ تغییری اعمال نشد.",
  transport_probe_failed: "تست getMe از مسیر جدید ناموفق بود؛ مسیر فعال تغییر نکرد.",
  transport_reconciliation_required: "وضعیت نامشخص است؛ از تلاش مجدد خودکار خودداری کنید و نتیجه را تطبیق دهید.",
  connection_change_in_progress: "یک تغییر فعال یا نیازمند بررسی وجود دارد؛ ابتدا آن را تعیین‌تکلیف کنید.",
  configuration_changed: "نسخهٔ فعال تغییر کرده است؛ فرم را تازه‌سازی کنید.",
  transport_config_unreadable: "کلید رمزنگاری سرور یا اطلاعات ذخیره‌شده نیازمند بررسی است.",
  security_service_unavailable: "سرویس احراز هویت موقتاً در دسترس نیست.",
  transport_worker_unavailable: "پردازشگر تغییر مسیر در این سرویس فعال نیست.",
};

const stateText: Record<State, string> = {
  pending: "پیشنهاد ثبت شده؛ هنوز فعال نیست",
  applying: "در حال تست و فعال‌سازی",
  succeeded: "تست و فعال‌سازی تأیید شد",
  failed: "ناموفق؛ مسیر قبلی حفظ شده",
  cancelled: "لغوشده",
  needs_review: "نامشخص؛ نیازمند تطبیق و بررسی",
};
const modeText: Record<Mode, string> = {
  direct: "Direct — اتصال مستقیم",
  http_proxy: "HTTP / SOCKS5 Proxy",
  cloudflare_worker: "Cloudflare Worker",
};

/**
 * Browser-side transport settings are transient until the user explicitly
 * stages them. Sensitive fields are never rendered back from PostgreSQL or
 * stored in URLs, localStorage, log messages or rendered operation history.
 */
export function TelegramTransportPanel({
  initial,
}: { initial: TelegramTransportData }) {
  const [data, setData] = useState(initial);
  const [mode, setMode] = useState<Mode>(initial.active.mode);
  const [proxyUrl, setProxyUrl] = useState(initial.active.proxy_url);
  const [workerUrl, setWorkerUrl] = useState(initial.active.worker_url);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{
    ok: boolean; text: string;
  } | null>(null);
  const [probe, setProbe] = useState<{
    changeId: string; id: string; milliseconds: number;
  } | null>(null);

  const load = useCallback(async () => {
    const response = await fetch("/api/admin/telegram-transport/status", {
      method: "GET", credentials: "same-origin",
      cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(20_000),
    });
    const value = await response.json() as TelegramTransportData;
    if (!response.ok || !value.active || !Array.isArray(value.history)) {
      throw new Error("خواندن وضعیت اتصال ممکن نشد.");
    }
    setData(value);
  }, []);

  const applying = data.history.some((row) => row.status === "applying");
  useEffect(() => {
    if (!applying) return;
    const timer = setInterval(() => {
      void load().catch(() => undefined);
    }, 4_000);
    return () => clearInterval(timer);
  }, [applying, load]);

  async function submit(
    operation: string, values: Record<string, unknown>,
    successMessage: string,
  ): Promise<void> {
    if (busy) return;
    setBusy(true); setNotice(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch(
        `/api/admin/telegram-transport/${operation}`, {
          method: "POST", credentials: "same-origin",
          cache: "no-store", redirect: "error",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-Shop-Login-Challenge": challenge,
          },
          body: JSON.stringify(values),
          signal: AbortSignal.timeout(
            operation === "apply" || operation === "reconcile" ? 75_000 : 28_000,
          ),
        },
      );
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
        throw new Error("پاسخ کنترل اتصال معتبر نیست؛ وضعیت را دوباره بخوانید.");
      }
      const result = await response.json() as Result;
      if (!response.ok || result.ok !== true) {
        const description = result.code && Object.hasOwn(errorText, result.code)
          ? errorText[result.code] : "عملیات تأیید نشد؛ وضعیت فعلی را بررسی کنید.";
        setNotice({ ok: false, text: description + (
          result.requestId ? ` (پیگیری: ${result.requestId})` : ""
        ) });
        return;
      }
      if (operation === "probe") {
        setProbe({
          changeId: String(values.change_id ?? ""),
          id: result.verified_bot_id ?? "نامشخص",
          milliseconds: result.round_trip_ms ?? 0,
        });
      } else {
        setProbe(null);
      }
      await load();
      setNotice({ ok: true, text: successMessage });
    } catch {
      // An unknown result may have applied; do not retry a mutation blindly.
      setNotice({
        ok: false,
        text: "پاسخ نهایی دریافت نشد. پیش از هر تلاش مجدد، «تازه‌سازی وضعیت» را بزنید.",
      });
    } finally {
      setBusy(false);
    }
  }

  function stage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const fields = new FormData(form);
    const payload = {
      mode, expected_version: data.active.version,
      proxy_url: mode === "http_proxy" ? proxyUrl : "",
      proxy_username: mode === "http_proxy"
        ? String(fields.get("proxy_username") ?? "").trim() : "",
      proxy_password: mode === "http_proxy"
        ? String(fields.get("proxy_password") ?? "") : "",
      worker_url: mode === "cloudflare_worker" ? workerUrl : "",
      worker_secret: mode === "cloudflare_worker"
        ? String(fields.get("worker_secret") ?? "") : "",
    };
    // Never store passwords in component state or include them in redirects.
    void submit(
      "stage", payload,
      "پیشنهاد رمزنگاری و ثبت شد. مسیر فعال هنوز تغییر نکرده است؛ ابتدا تست و سپس تأیید کنید.",
    ).finally(() => {
      form.querySelectorAll<HTMLInputElement>('input[type="password"]')
        .forEach((field) => { field.value = ""; });
    });
  }

  const pending = data.history.find((row) =>
    row.status === "pending" || row.status === "applying" ||
    row.status === "needs_review"
  );
  const proxyOptions = data.approved_proxy_urls;
  const workerOptions = data.approved_worker_origins;

  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <Network className="size-5 text-primary" />
        مسیر API تلگرام: Direct، Proxy و Cloudflare Worker
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-6">
      <div className="grid gap-3 rounded-xl border bg-muted/30 p-4 text-sm md:grid-cols-2">
        <p>مسیر فعال: <strong dir="ltr">{modeText[data.active.mode]}</strong></p>
        <p>نسخهٔ تأییدشده: <strong>{data.active.version}</strong></p>
        <p>منبع تنظیم: {data.active.source === "deployment" ? "Deployment / ENV" : "PostgreSQL رمزنگاری‌شده"}</p>
        <p>آخرین تأیید: {data.active.verified_at
          ? new Date(data.active.verified_at).toLocaleString("fa-IR") : "فعلاً فقط تنظیم اولیه"}</p>
        <p className="md:col-span-2">آدرس فعال: <span dir="ltr" className="break-all">
          {data.active.mode === "http_proxy" ? data.active.proxy_url :
            data.active.mode === "cloudflare_worker" ? data.active.worker_url :
              "api.telegram.org"}
        </span></p>
        {data.active.verified_bot_id ? <p className="md:col-span-2">
          شناسهٔ بات تأییدشده: <b dir="ltr">{data.active.verified_bot_id}</b>
        </p> : null}
      </div>

      <p className="flex items-start gap-2 text-xs leading-7 text-muted-foreground">
        <ShieldCheck className="mt-1 size-4 shrink-0" />
        این قسمت فقط مسیر خروجی Telegram Bot API را تغییر می‌دهد؛ روش دریافت
        Webhook/getUpdates و اتصال بله، به‌صورت مستقل مدیریت می‌شوند.
        Token ربات در پنل دریافت یا نمایش داده نمی‌شود.
      </p>

      {notice ? <p role={notice.ok ? "status" : "alert"}
        className={`rounded-lg border p-3 text-sm leading-7 ${notice.ok ? "bg-muted" : "bg-destructive/10 text-destructive"}`}>
        {notice.ok ? <CheckCircle2 className="me-2 inline size-4" /> :
          <ShieldAlert className="me-2 inline size-4" />}
        {notice.text}
      </p> : null}

      <form onSubmit={stage} className="space-y-4">
        <fieldset disabled={busy || Boolean(pending)} className="space-y-4">
          <label className="block space-y-2 text-sm font-medium">روش اتصال
            <select value={mode} onChange={(event) => setMode(event.target.value as Mode)}
              className="h-10 w-full rounded-md border border-input bg-background px-3">
              <option value="direct">Direct — مستقیم به Telegram API</option>
              <option value="http_proxy">HTTP / SOCKS5 Proxy</option>
              <option value="cloudflare_worker">Cloudflare Worker</option>
            </select>
          </label>

          {mode === "http_proxy" ? <div className="grid gap-4 rounded-lg border p-4 sm:grid-cols-2">
            <label className="block space-y-2 text-sm sm:col-span-2">Proxy Endpoint
              <select value={proxyUrl} onChange={(event) => setProxyUrl(event.target.value)}
                required className="h-10 w-full rounded-md border bg-background px-3 text-sm" dir="ltr">
                <option value="">انتخاب Proxy تأییدشده</option>
                {proxyOptions.map((url) => <option key={url} value={url}>{url}</option>)}
              </select>
            </label>
            <label className="block space-y-2 text-sm">Proxy Username (اختیاری)
              <Input name="proxy_username" dir="ltr" maxLength={128} autoComplete="off"
                defaultValue={data.active.proxy_username}
                placeholder="username" />
            </label>
            <label className="block space-y-2 text-sm">Proxy Password
              <Input name="proxy_password" type="password" dir="ltr" maxLength={256}
                autoComplete="new-password"
                placeholder={data.active.has_proxy_password
                  ? "خالی = حفظ رمز فعلی همان Proxy" : "اختیاری در اتصال بدون احراز هویت"} />
            </label>
            {!proxyOptions.length ? <p className="sm:col-span-2 text-xs text-destructive">
              هیچ Proxy مجازی در Deployment ثبت نشده است. ابتدا
              TELEGRAM_PROXY_ALLOWED_ENDPOINTS را به‌صورت محدود تعریف کنید.
            </p> : null}
          </div> : null}

          {mode === "cloudflare_worker" ? <div className="space-y-4 rounded-lg border p-4">
            <label className="block space-y-2 text-sm">Worker HTTPS Origin
              <select value={workerUrl} onChange={(event) => setWorkerUrl(event.target.value)}
                required className="h-10 w-full rounded-md border bg-background px-3 text-sm" dir="ltr">
                <option value="">انتخاب Worker تأییدشده</option>
                {workerOptions.map((url) => <option key={url} value={url}>{url}</option>)}
              </select>
            </label>
            <label className="block space-y-2 text-sm">Relay Key (Secret)
              <Input name="worker_secret" type="password" dir="ltr"
                maxLength={256} autoComplete="new-password"
                placeholder={data.active.has_worker_secret
                  ? "خالی = حفظ کلید فعلی همین Worker" : "حداقل ۳۲ نویسه"} />
            </label>
            {!workerOptions.length ? <p className="text-xs text-destructive">
              Worker تأییدشده‌ای وجود ندارد. Origin را ابتدا در
              TELEGRAM_WORKER_ALLOWED_ORIGINS ثبت کنید.
            </p> : null}
          </div> : null}
          <p className="text-xs leading-7 text-muted-foreground">
            <LockKeyhole className="me-1 inline size-4" />
            آدرس‌های مجاز از تنظیمات امن سرور انتخاب می‌شوند تا Token به
            Proxy یا Worker دلخواه و تأییدنشده فرستاده نشود.
            رمزها در PostgreSQL با Fernet نگهداری می‌شوند.
          </p>
          <Button type="submit" disabled={busy || Boolean(pending)}>
            <ShieldCheck className="size-4" /> ثبت پیشنهاد (بدون فعال‌سازی)
          </Button>
        </fieldset>
      </form>

      {pending ? <section className="space-y-4 rounded-xl border p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <strong className="text-sm">آخرین پیشنهاد: {modeText[pending.proposed.mode]}</strong>
          <span className="text-xs text-muted-foreground">{stateText[pending.status]}</span>
        </div>
        <p className="text-xs text-muted-foreground" dir="ltr">{pending.id}</p>
        {pending.status === "pending" ? <>
          <p className="text-xs leading-7 text-muted-foreground">
            ابتدا «تست getMe» را اجرا کنید. تست به‌تنهایی مسیر فعال را
            تغییر نمی‌دهد؛ برای اعمال واقعی رمز حساب و MFA لازم است.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={busy}
              onClick={() => void submit("probe", { change_id: pending.id },
                "تست getMe موفق بود، اما هنوز مسیر فعال تغییر نکرده است.")}>
              <TestTube2 className="size-4" /> تست اتصال جدید
            </Button>
            <Button type="button" variant="outline" disabled={busy}
              onClick={() => void submit("cancel", { change_id: pending.id },
                "پیشنهاد لغو شد؛ مسیر قبلی تغییر نکرده است.")}>
              لغو پیشنهاد
            </Button>
          </div>
          {probe?.changeId === pending.id ? <p role="status" className="text-sm">
            getMe: شناسه <b dir="ltr">{probe.id}</b> · زمان پاسخ: {probe.milliseconds} ms
          </p> : null}
          <form onSubmit={(event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const fields = new FormData(form);
            void submit("apply", {
              change_id: pending.id,
              current_password: String(fields.get("current_password") ?? ""),
              second_factor: String(fields.get("second_factor") ?? ""),
            }, "تست هویت بات و فعال‌سازی مسیر جدید درحال‌اجرا تأیید شد.")
              .finally(() => form.reset());
          }} className="grid gap-3 md:grid-cols-2">
            <label className="block space-y-2 text-sm">رمز فعلی مدیر
              <Input name="current_password" type="password" required
                maxLength={256} autoComplete="current-password" dir="ltr" disabled={busy} />
            </label>
            <label className="block space-y-2 text-sm">کد MFA یا بازیابی
              <Input name="second_factor" required maxLength={64}
                autoComplete="one-time-code" dir="ltr" disabled={busy} />
            </label>
            <div className="md:col-span-2">
              <Button type="submit" disabled={busy}>
                <Wifi className="size-4" /> تأیید هویت و فعال‌سازی
              </Button>
            </div>
          </form>
        </> : pending.status === "needs_review" ? <div className="space-y-3">
          <p className="text-sm text-destructive">
            نتیجهٔ یک عملیات قطع‌شده نامشخص است. تغییر قبلی تکرار نمی‌شود.
            فقط پس از بررسی مسیر تأییدشدهٔ فعال، می‌توان رکورد را تطبیق داد.
          </p>
          <form onSubmit={(event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const fields = new FormData(form);
            void submit("reconcile", {
              change_id: pending.id,
              current_password: String(fields.get("current_password") ?? ""),
              second_factor: String(fields.get("second_factor") ?? ""),
            }, "مسیر تأییدشدهٔ قبلی بررسی و وضعیت نامشخص تعیین‌تکلیف شد.")
              .finally(() => form.reset());
          }} className="grid gap-3 md:grid-cols-2">
            <label className="space-y-2 text-sm">رمز حساب
              <Input name="current_password" type="password" required
                autoComplete="current-password" />
            </label>
            <label className="space-y-2 text-sm">کد MFA
              <Input name="second_factor" required autoComplete="one-time-code" />
            </label>
            <Button type="submit" disabled={busy} variant="outline"
              className="md:col-span-2 md:justify-self-start">
              <RefreshCcw className="size-4" /> تطبیق بدون تکرار تغییر
            </Button>
          </form>
        </div> : <p className="text-sm">نتیجهٔ تغییر را تازه‌سازی کنید.</p>}
      </section> : null}

      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong className="text-sm">تاریخچهٔ تغییرات رمزنگاری‌شده</strong>
          <Button type="button" size="sm" variant="outline" disabled={busy}
            onClick={() => void load().then(() => setNotice({
              ok: true, text: "وضعیت ثبت‌شدهٔ سرور تازه‌سازی شد.",
            })).catch(() => setNotice({
              ok: false, text: "تازه‌سازی وضعیت انجام نشد.",
            }))}>
            <RefreshCcw className="size-4" /> تازه‌سازی وضعیت
          </Button>
        </div>
        {data.history.map((change) => <div key={change.id}
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
          <div className="min-w-0">
            <p><strong>{modeText[change.proposed.mode]}</strong> · {stateText[change.status]}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {new Date(change.updated_at).toLocaleString("fa-IR")} ·
              {change.operation === "rollback" ? " بازگشت ثبت‌شده" : " تغییر جدید"}
            </p>
            {change.error_code ? <p className="mt-1 text-xs text-destructive" dir="ltr">
              {change.error_code}
            </p> : null}
          </div>
          {change.status === "succeeded" && !pending
            ? <Button type="button" variant="outline" size="sm" disabled={busy}
              onClick={() => void submit("rollback", {
                source_change_id: change.id,
                expected_version: data.active.version,
              }, "بازگشت به تنظیم قبلی فقط پیشنهاد شد؛ برای اعمال، تست و تأیید هویت لازم است.")}>
              <RotateCcw className="size-4" /> پیشنهاد بازگشت
            </Button> : null}
        </div>)}
        {!data.history.length ? <p className="text-sm text-muted-foreground">
          هنوز هیچ تغییر مسیر از پنل ثبت نشده است.
        </p> : null}
      </div>

      <p className="flex items-start gap-2 text-xs leading-7 text-muted-foreground">
        <CircleHelp className="mt-1 size-4 shrink-0" />
        تغییر Direct / Proxy / Worker فقط مسیر خروجی تلگرام را عوض می‌کند.
        تنظیمات دریافت Webhook و getUpdates در بخش پایین مستقل هستند.
        در صورت خطای Timeout، نتیجهٔ عملیات را پیش از تلاش دوباره بررسی کنید.
      </p>
    </CardContent>
  </Card>;
}
