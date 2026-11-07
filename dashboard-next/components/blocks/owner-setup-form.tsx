"use client";

import { type FormEvent, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestBrowserChallenge } from "@/lib/browser-challenge";

const subscribe = () => () => {};
const ready = () => true;
const notReady = () => false;

const errors: Record<string, string> = {
  invalid_setup_code: "کد راه‌اندازی نامعتبر یا منقضی شده است. از ترمینال کد تازه بگیرید.",
  invalid_request: "نام کاربری، رمز و کد راه‌اندازی را بررسی کنید.",
  password_policy_failed: "رمز عبور با سیاست رمز این نصب سازگار نیست.",
  security_check_failed: "درخواست تأیید نشد. صفحه را دوباره بارگذاری کنید.",
};

export function OwnerSetupForm() {
  const hydrated = useSyncExternalStore(subscribe, ready, notReady);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const username = String(fields.get("username") ?? "").trim().toLowerCase();
    const password = String(fields.get("password") ?? "");
    const setupCode = String(fields.get("setup_code") ?? "").trim();
    if (password !== fields.get("confirm_password")) {
      setError("رمز عبور و تکرار آن یکسان نیستند.");
      return;
    }
    setError("");
    setWorking(true);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/auth/owner-setup", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: { "Content-Type": "application/json", "X-Shop-Login-Challenge": challenge },
        body: JSON.stringify({ username, password, setup_code: setupCode }),
        signal: AbortSignal.timeout(20_000),
      });
      const reply = await response.json() as { ok?: boolean; code?: string };
      const created = response.status === 201 && reply.ok === true;
      const configured = response.status === 409 && reply.code === "owner_already_configured";
      if (created || configured) {
        form.reset();
        // A fresh request sees the committed owner instead of a cached setup page.
        window.location.replace("/login");
      } else {
        setError(errors[reply.code ?? ""] ?? "نتیجه مشخص نیست. صفحه را دوباره بارگذاری کنید.");
      }
    } catch {
      setError("نتیجه مشخص نیست. صفحه را دوباره بارگذاری کنید.");
    } finally {
      setWorking(false);
    }
  }

  return (
    <form method="post" onSubmit={submit} className="space-y-4" aria-busy={working}>
      <p className="text-sm text-muted-foreground">
        کد ۱۵ دقیقه‌ای را از ترمینال خصوصی این نصب بگیرید.
      </p>
      <code dir="ltr" className="block break-all rounded-md bg-muted p-2 text-start text-xs">
        python3 scripts/codespace_setup.py owner-setup-code
      </code>
      <div className="space-y-1.5">
        <label htmlFor="setup-code" className="text-sm font-medium">کد راه‌اندازی</label>
        <Input id="setup-code" name="setup_code" type="password" dir="ltr" autoComplete="off" required />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="setup-username" className="text-sm font-medium">نام کاربری دلخواه</label>
        <Input id="setup-username" name="username" dir="ltr" autoComplete="username"
          autoCapitalize="none" spellCheck={false} minLength={3} maxLength={80} required />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="setup-password" className="text-sm font-medium">رمز عبور جدید</label>
        <Input id="setup-password" name="password" type="password" dir="ltr"
          autoComplete="new-password" minLength={12} maxLength={256} required />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="setup-confirm" className="text-sm font-medium">تکرار رمز عبور</label>
        <Input id="setup-confirm" name="confirm_password" type="password" dir="ltr"
          autoComplete="new-password" minLength={12} maxLength={256} required />
      </div>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={!hydrated || working} className="w-full">
        {working ? "در حال ساخت حساب…" : "ساخت حساب مدیر"}
      </Button>
    </form>
  );
}
