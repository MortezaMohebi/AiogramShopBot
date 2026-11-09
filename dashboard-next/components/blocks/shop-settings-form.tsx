"use client";

import { useState } from "react";
import { DraftForm, type DraftReceipt } from "@/components/blocks/draft-form";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
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
  service_unavailable: "پاسخ سرور دریافت نشد. پیش از تلاش دوباره، تنظیمات فعلی را بررسی کنید.",
  save_failed: "پاسخ ذخیره تأیید نشد. قبل از تلاش دوباره وضعیت فعلی را بررسی کنید.",
};

/** Show real save status, never claim success until FastAPI confirms a read-back. */
export function ShopSettingsForm({ initial }: { initial: ShopSettings }) {
  const [saved, setSaved] = useState(initial);

  async function save(values: FormData): Promise<DraftReceipt> {
    const payload: ShopSettings = {
      brand_name: String(values.get("brand_name") ?? "").trim(),
      welcome_message: String(values.get("welcome_message") ?? "").trim(),
      faq_text: String(values.get("faq_text") ?? "").trim(),
      support_url: String(values.get("support_url") ?? "").trim(),
    };
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
        return { ok: false, message: messages[code], requestId: result.requestId };
      }
      if (!result.settings) return { ok: false, code: "outcome_unknown" };
      setSaved(result.settings);
      return { ok: true, data: null };
    } catch {
      return { ok: false, message: "ارتباط با سرور برقرار نشد. وضعیت فعلی تنظیمات را بررسی کنید." };
    }
  }

  return (
    <DraftForm saveAction={save} className="space-y-5">
      <label className="block space-y-2 text-sm font-medium">
        نام فروشگاه
        <Input name="brand_name" maxLength={255} defaultValue={saved.brand_name ?? ""} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        پیام خوش‌آمدگویی
        <Textarea name="welcome_message" rows={5} maxLength={4096} defaultValue={saved.welcome_message ?? ""} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        پرسش‌های متداول
        <Textarea name="faq_text" rows={7} maxLength={20000} defaultValue={saved.faq_text ?? ""} />
      </label>
      <label className="block space-y-2 text-sm font-medium">
        لینک پشتیبانی (HTTPS)
        <Input
          name="support_url" dir="ltr" type="url" className="text-start"
          maxLength={500} defaultValue={saved.support_url ?? ""}
          placeholder="https://..."
        />
      </label>
    </DraftForm>
  );
}
