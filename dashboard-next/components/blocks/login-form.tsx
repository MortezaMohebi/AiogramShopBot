"use client";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, Eye, EyeOff, LoaderCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CaptchaChallenge, type CaptchaChallengeHandle } from "@/components/blocks/captcha-challenge";
import type { PublicCaptchaConfig } from "@/lib/captcha-types";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { type LoginErrorCode, loginErrorMessages, normalizeLoginError } from "@/lib/login-errors";
interface Props { initialError?: string | null; captcha: PublicCaptchaConfig }
interface Issue { code: LoginErrorCode; requestId?: string }
/** CAPTCHA remains optional; MFA and the revocable session are verified in Python. */
export function LoginForm({ initialError, captcha }: Props) {
  const [issue, setIssue] = useState<Issue | null>(initialError ? { code: normalizeLoginError(initialError) } : null);
  const [working, setWorking] = useState(false), [showPassword, setShowPassword] = useState(false);
  const [phase, setPhase] = useState<"security" | "login">("security");
  const errorRef = useRef<HTMLDivElement>(null), captchaRef = useRef<CaptchaChallengeHandle>(null);
  useEffect(() => { if (issue) errorRef.current?.focus(); }, [issue]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (working) return;
    const form = event.currentTarget, data = new FormData(form);
    const username = String(data.get("username") ?? "").trim().toLowerCase();
    const password = String(data.get("password") ?? ""), second_factor = String(data.get("second_factor") ?? "").trim();
    if (!/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(username) || !password || password.length > 256 || second_factor.length > 64) { setIssue({ code: "invalid_request" }); return; }
    setIssue(null); setWorking(true); setPhase("security");
    try {
      const challenge = await requestBrowserChallenge(), captchaToken = await captchaRef.current?.getToken();
      if (captcha.provider !== "none" && !captchaToken) throw new Error("captcha_unavailable");
      setPhase("login");
      const response = await fetch("/api/auth/login", {
        method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Shop-Login-Challenge": challenge },
        body: JSON.stringify({ username, password, second_factor, captchaToken }), signal: AbortSignal.timeout(25_000),
      });
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new Error("network_unavailable");
      const result: unknown = await response.json();
      if (!result || typeof result !== "object") throw new Error("service_unavailable");
      const reply = result as { ok?: boolean; redirect?: string; code?: string; requestId?: string };
      if (!response.ok || reply.ok !== true) {
        const code = normalizeLoginError(reply.code);
        setIssue({ code, requestId: typeof reply.requestId === "string" && /^[a-f0-9-]{36}$/i.test(reply.requestId) ? reply.requestId : undefined });
        captchaRef.current?.reset();
        if (code === "invalid_credentials") { const input = form.elements.namedItem("password"); if (input instanceof HTMLInputElement) input.value = ""; }
        return;
      }
      if (!["/dashboard", "/account?enroll=1"].includes(reply.redirect ?? "")) throw new Error("service_unavailable");
      // A fresh navigation avoids a cached unauthenticated RSC tree.
      window.location.replace(reply.redirect);
    } catch (error) {
      captchaRef.current?.reset();
      const known = ["captcha_required", "captcha_unavailable", "security_check_failed", "service_unavailable"];
      setIssue({ code: error instanceof Error && known.includes(error.message) ? normalizeLoginError(error.message) : "network_unavailable" });
    } finally { setWorking(false); }
  }
  const message = issue ? loginErrorMessages[issue.code] : null;
  return <form action="/api/auth/login" method="post" onSubmit={submit} className="space-y-5" aria-busy={working}>
    {message ? <div ref={errorRef} tabIndex={-1} role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive focus:outline-none">
      <div className="flex items-start gap-2"><AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" /><div className="space-y-1">
        <p className="font-semibold">{message.title}</p><p className="leading-7">{message.description}</p>
        {issue?.requestId ? <p dir="ltr" className="text-xs">Request ID: {issue.requestId}</p> : null}
        {issue?.code === "security_check_failed" ? <a href="/login" className="underline">بازکردن دوبارهٔ صفحهٔ ورود</a> : null}
      </div></div>
    </div> : null}
    <div className="space-y-2"><label htmlFor="username" className="text-sm font-medium">نام کاربری</label>
      <Input id="username" name="username" dir="ltr" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} minLength={3} maxLength={80} disabled={working} required />
    </div>
    <div className="space-y-2"><label htmlFor="password" className="text-sm font-medium">رمز عبور</label>
      <div className="relative" dir="ltr">
        <Input id="password" name="password" type={showPassword ? "text" : "password"} dir="ltr" autoComplete="current-password" minLength={1} maxLength={256} className="ps-12 text-start" disabled={working} required />
        <button type="button" aria-label={showPassword ? "مخفی‌کردن رمز عبور" : "نمایش رمز عبور"} aria-pressed={showPassword} className="absolute start-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" onClick={() => setShowPassword((value) => !value)} disabled={working}>
          {showPassword ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
        </button>
      </div>
    </div>
    <div className="space-y-2"><label htmlFor="second-factor" className="text-sm font-medium">کد احراز هویت یا بازیابی (اگر فعال است)</label>
      <Input id="second-factor" name="second_factor" dir="ltr" autoComplete="one-time-code" maxLength={64} disabled={working} />
    </div>
    <CaptchaChallenge ref={captchaRef} config={captcha} />
    <Button type="submit" size="lg" className="w-full" disabled={working || captcha.provider === "unavailable"}>{working ? <><LoaderCircle aria-hidden="true" className="size-4 animate-spin" />{phase === "security" ? "در حال بررسی امنیت ورود..." : "در حال ورود..."}</> : <>ورود امن <ArrowLeft aria-hidden="true" className="size-4" /></>}</Button>
    <p className="text-center text-xs leading-6 text-muted-foreground">اطلاعات ورود فقط از مسیر HTTPS به سرویس مدیریت ارسال می‌شوند.</p>
  </form>;
}
