"use client";

import { type FormEvent, useState } from "react";
import { CheckCircle2, LoaderCircle, TriangleAlert } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ShopSettings } from "@/lib/types";

type Code =
  | "invalid_request"
  | "security_check_failed"
  | "session_expired"
  | "permission_denied"
  | "service_unavailable"
  | "save_failed";

interface Result {
  ok?: boolean;
  code?: Code;
  requestId?: string;
  settings?: ShopSettings;
}

const messages: Record<Code, string> = {
  invalid_request: "اطلاعات واردشده معتبر نیست. طول متن‌ها و نشانی HTTPS را بررسی کنید.",
  security_check_failed: "بررسی امنیتی انجام نشد. این صفحه را دوباره باز و تلاش کنید.",
  session_expired: "نشست شما پایان یافته است. ابتدا دوباره وارد حساب خود شوید.",
  permission_denied: "حساب شما مجوز تغییر تنظیمات فروشگاه را ندارد.",
  service_unavailable: "ارتباط امن با سرور برقرار نشد. از وضعیت داده‌ها اطمینان حاصل کنید.",
  save_failed: "پاسخ ذخیره تأیید نشد. قبل از تلاش دوباره وضعیت فعلی را بررسی کنید.",
};

/** Show real save status, never claim success until FastAPI confirms a read-back. */
export function ShopSettingsForm({ initial }: { initial: ShopSettings }) {
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<{
    ok: boolean;
    text: string;
    requestId?: string;
  } | null>(null);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;

    const form = event.currentTarget;
    if (!form.reportValidity()) return;

    const values = new FormData(form);
    const payload: ShopSettings = {
      brand_name: String(values.get("brand_name") ?? "").trim(),
      welcome_message: String(values.get("welcome_message") ?? "").trim(),
      faq_text: String(values.get("faq_text") ?? "").trim(),
      support_url: String(values.get("support_url") ?? "").trim(),
    };
    setSaving(true);
    setOutcome(null);
    try {
      const csrf = await requestBrowserChallenge();
      const response = await fetch("/api/admin/shop-settings", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": csrf,
        },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(25_000),
      });

      if (
        !(response.headers.get("content-type") ?? "").includes("application/json")
      ) throw new Error("service_unavailable");

      const result = (await response.json()) as Result;
      if (!response.ok || result.ok !== true) {
        const code =
          result.code && Object.hasOwn(messages, result.code)
            ? result.code
            : "service_unavailable";
        setOutcome({
          ok: false,
          text: messages[code],
          requestId: result.requestId,
        });
        return;
      }
      setOutcome({ ok: true, text: "تنظیمات با موفقیت در پایگاه داده ذخیره شد." });
    } catch {
      setOutcome({
        ok: false,
        text: "ارتباط با سرور برقرار نشد. وضعیت فعلی تنظیمات را بررسی کنید.",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="space-y-5" aria-busy={saving}>
      <label className="block space-y-2 text-sm font-medium">
        نام فروشگاه
        <Input name="brand_name" maxLength={255} defaultValue={initial.brand_name ?? ""} disabled={saving} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        پیام خوش‌آمدگویی
        <Textarea name="welcome_message" rows={5} maxLength={4096} defaultValue={initial.welcome_message ?? ""} disabled={saving} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        پرسش‌های متداول
        <Textarea name="faq_text" rows={7} maxLength={20000} defaultValue={initial.faq_text ?? ""} disabled={saving} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        لینک پشتیبانی (HTTPS)
        <Input
          name="support_url" dir="ltr" type="url" className="text-start"
          maxLength={500} defaultValue={initial.support_url ?? ""}
          placeholder="https://..." disabled={saving}
        />
      </label>
      {outcome ? (
        <div
          role={outcome.ok ? "status" : "alert"}
          className={
            outcome.ok
              ? "flex items-start gap-2 rounded-lg bg-accent p-3 text-sm text-accent-foreground"
              : "flex items-start gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
          }
        >
          {outcome.ok
            ? <CheckCircle2 aria-hidden="true" className="mt-1 size-4 shrink-0" />
            : <TriangleAlert aria-hidden="true" className="mt-1 size-4 shrink-0" />}
          <div>
            <p>{outcome.text}</p>
            {outcome.requestId ? (
              <p dir="ltr" className="mt-2 text-xs">Request ID: {outcome.requestId}</p>
            ) : null}
            {outcome.ok === false && outcome.text === messages.session_expired ? (
              <a href="/login" className="mt-2 inline-block underline">ورود مجدد</a>
            ) : null}
          </div>
        </div>
      ) : null}
      <Button type="submit" disabled={saving}>
        {saving ? (
          <>
            <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
            در حال ذخیره و تأیید...
          </>
        ) : "ذخیره تنظیمات"}
      </Button>
    </form>
  );
}
