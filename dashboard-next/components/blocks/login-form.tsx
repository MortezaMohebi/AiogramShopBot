"use client";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AlertCircle, Eye, EyeOff } from "lucide-react";
import { ActivityIndicator } from "@/components/ui/activity-indicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CaptchaChallenge, type CaptchaChallengeHandle } from "@/components/blocks/captcha-challenge";
import type { PublicCaptchaConfig } from "@/lib/captcha-types";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { offerPasswordStorage } from "@/lib/password-storage";
import { type LoginErrorCode, loginErrorMessages, normalizeLoginError } from "@/lib/login-errors";
interface Props { initialError?: string | null; captcha: PublicCaptchaConfig }
interface Issue { code: LoginErrorCode; requestId?: string }
interface PendingCredentials { username: string; password: string; rememberMe: boolean; expiresAt: number }
/** Convert supported authenticator digits and copied whitespace only. */
export function normalizeAuthenticatorCode(value: string): string {
  const digits = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩";
  return value.replace(/[۰-۹٠-٩]/g, digit => String(digits.indexOf(digit) % 10)).replace(/\s/g, "");
}
/** CAPTCHA remains optional; MFA and the revocable session are verified in Python. */
export function LoginForm({ initialError, captcha }: Props) {
  const [issue, setIssue] = useState<Issue | null>(initialError ? { code: normalizeLoginError(initialError) } : null);
  const [working, setWorking] = useState(false), [showPassword, setShowPassword] = useState(false);
  const [phase, setPhase] = useState<"security" | "login">("security");
  const [step, setStep] = useState<"credentials" | "mfa">("credentials");
  const [method, setMethod] = useState<"authenticator" | "recovery">("authenticator");
  const [username, setUsername] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const pending = useRef<PendingCredentials | null>(null);
  const activeRequest = useRef<AbortController | null>(null), generation = useRef(0);
  const factorRef = useRef<HTMLInputElement>(null);
  const errorRef = useRef<HTMLDivElement>(null), captchaRef = useRef<CaptchaChallengeHandle>(null);
  const restart = useCallback((code?: LoginErrorCode) => {
    generation.current += 1; activeRequest.current?.abort(); activeRequest.current = null;
    pending.current = null; setWorking(false); setShowPassword(false);
    setStep("credentials"); setMethod("authenticator"); setIssue(code ? { code } : null);
    captchaRef.current?.reset();
  }, []);
  useEffect(() => { if (issue) errorRef.current?.focus(); }, [issue]);
  useEffect(() => {
    if (step !== "mfa") return;
    factorRef.current?.focus();
    const timer = window.setTimeout(() => { if (pending.current) restart("login_expired"); }, Math.max(0, (pending.current?.expiresAt ?? 0) - Date.now()));
    return () => window.clearTimeout(timer);
  }, [step, restart]);
  useEffect(() => () => {
    // Pending passwords never enter URL/history, app storage or hidden fields.
    pending.current = null; generation.current += 1; activeRequest.current?.abort();
  }, []);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (working) return;
    const form = event.currentTarget, data = new FormData(form);
    const verifying = step === "mfa", held = pending.current;
    if (verifying && (!held || held.expiresAt <= Date.now())) { restart("login_expired"); return; }
    const loginName = verifying ? held!.username : String(data.get("username") ?? "").trim().toLowerCase();
    const password = verifying ? held!.password : String(data.get("password") ?? "");
    const persistent = verifying ? held!.rememberMe : rememberMe;
    const rawFactor = verifying ? String(data.get("second_factor") ?? "").trim() : "";
    const second_factor = method === "authenticator" ? normalizeAuthenticatorCode(rawFactor) : rawFactor;
    if (!/^[a-z0-9][a-z0-9_.-]{2,79}$/.test(loginName) || !password || password.length > 256) { setIssue({ code: "invalid_request" }); return; }
    if (verifying && (!second_factor || second_factor.length > 64 || (method === "authenticator" && !/^[0-9]{6}$/.test(second_factor)))) { setIssue({ code: "invalid_verification" }); return; }
    setUsername(loginName); setIssue(null); setWorking(true); setPhase("security");
    const request = new AbortController(), attempt = ++generation.current;
    activeRequest.current = request;
    const timer = window.setTimeout(() => request.abort(), 25_000);
    try {
      const challenge = await requestBrowserChallenge(), captchaToken = await captchaRef.current?.getToken();
      if (attempt !== generation.current) return;
      if (request.signal.aborted) throw new Error("network_unavailable");
      if (captcha.provider !== "none" && !captchaToken) throw new Error("captcha_unavailable");
      setPhase("login");
      const response = await fetch("/api/auth/login", {
        method: "POST", credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-Shop-Login-Challenge": challenge },
        body: JSON.stringify({ username: loginName, password, second_factor, captchaToken, remember_me: persistent }), signal: request.signal,
      });
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) throw new Error("network_unavailable");
      const result: unknown = await response.json();
      if (attempt !== generation.current) return;
      if (!result || typeof result !== "object") throw new Error("service_unavailable");
      const reply = result as { ok?: boolean; redirect?: string; code?: string; requestId?: string };
      // Python sends 428 only after checking the password; it creates no session.
      // Every MFA submission still revalidates the password and second factor.
      if (response.status === 428 && reply.ok === false && reply.code === "mfa_required" && !verifying) {
        pending.current = { username: loginName, password, rememberMe: persistent, expiresAt: Date.now() + 5 * 60 * 1000 };
        form.reset(); setShowPassword(false); setMethod("authenticator"); setStep("mfa");
        captchaRef.current?.reset(); return;
      }
      if (!response.ok || reply.ok !== true) {
        const code = normalizeLoginError(reply.code);
        if (verifying && (code === "invalid_credentials" || code === "temporarily_locked")) { restart(code); return; }
        setIssue({ code, requestId: typeof reply.requestId === "string" && /^[a-f0-9-]{36}$/i.test(reply.requestId) ? reply.requestId : undefined });
        captchaRef.current?.reset();
        // Keep the failed form/value present. Clearing/removing a password field
        // can look like successful AJAX login to native password managers.
        return;
      }
      if (reply.redirect !== "/dashboard" && reply.redirect !== "/account?enroll=1") throw new Error("service_unavailable");
      pending.current = null;
      await offerPasswordStorage(loginName, password);
      if (attempt !== generation.current) return;
      // A fresh navigation avoids a cached unauthenticated RSC tree.
      window.location.replace(reply.redirect);
    } catch (error) {
      if (attempt !== generation.current) return;
      captchaRef.current?.reset();
      const known = ["captcha_required", "captcha_unavailable", "security_check_failed", "service_unavailable"];
      setIssue({ code: error instanceof Error && known.includes(error.message) ? normalizeLoginError(error.message) : "network_unavailable" });
    } finally {
      window.clearTimeout(timer);
      if (attempt === generation.current) { setWorking(false); activeRequest.current = null; }
    }
  }
  const message = issue ? loginErrorMessages[issue.code] : null;
  return <form id="login" action="/api/auth/login" method="post" onSubmit={submit} className="space-y-5" aria-busy={working}>
    <h1 id="login-title" className="mb-7 text-2xl font-bold">{step === "mfa" ? "تأیید دومرحله‌ای" : "ورود به پنل مدیریت"}</h1>
    {step === "mfa" ? <p className="text-sm leading-7 text-muted-foreground">ورود به حساب <bdi className="font-semibold text-foreground">{username}</bdi></p> : null}
    {message ? <div id="login-error" ref={errorRef} tabIndex={-1} role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive focus:outline-none">
      <div className="flex items-start gap-2"><AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" /><div className="space-y-1">
        <p className="font-semibold">{message.title}</p><p className="leading-7">{message.description}</p>
        {issue?.requestId ? <details className="text-xs"><summary className="cursor-pointer py-1">اطلاعات پشتیبانی</summary><p dir="ltr" className="break-all py-1">Request ID: {issue.requestId}</p></details> : null}
        {issue?.code === "security_check_failed" ? <a href="/login" className="underline">بازکردن دوبارهٔ صفحهٔ ورود</a> : null}
      </div></div>
    </div> : null}
    {step === "credentials" ? <>
    <div className="space-y-2"><label htmlFor="username" className="text-sm font-medium">نام کاربری</label>
      <Input id="username" name="username" defaultValue={username} aria-invalid={issue?.code === "invalid_credentials" || issue?.code === "invalid_request"} aria-describedby={issue ? "login-error" : undefined} dir="ltr" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={false} minLength={3} maxLength={80} disabled={working} required />
    </div>
    <div className="space-y-2"><label htmlFor="password" className="text-sm font-medium">رمز عبور</label>
      <div className="relative" dir="ltr">
        <Input id="password" name="password" aria-invalid={issue?.code === "invalid_credentials"} aria-describedby={issue ? "login-error" : undefined} type={showPassword ? "text" : "password"} dir="ltr" autoComplete="current-password" minLength={1} maxLength={256} className="ps-12 text-start" disabled={working} required />
        <button type="button" aria-label={showPassword ? "مخفی‌کردن رمز عبور" : "نمایش رمز عبور"} aria-pressed={showPassword} className="absolute start-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring" onClick={() => setShowPassword((value) => !value)} disabled={working}>
          {showPassword ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
        </button>
      </div>
    </div>
    <label className="flex cursor-pointer items-center gap-3 text-sm">
      <input type="checkbox" name="remember_me" checked={rememberMe} disabled={working} onChange={event => setRememberMe(event.target.checked)} className="size-4 shrink-0 accent-primary" />
      مرا به خاطر بسپار
    </label>
    </> : <>
    <div className="space-y-2"><label htmlFor="second-factor" className="text-sm font-medium">{method === "authenticator" ? "کد تأیید" : "کد بازیابی"}</label>
      <Input key={method} ref={factorRef} id="second-factor" name="second_factor" dir="ltr" autoComplete={method === "authenticator" ? "one-time-code" : "off"} inputMode={method === "authenticator" ? "numeric" : "text"} spellCheck={false} autoCapitalize="none" aria-invalid={issue?.code === "invalid_verification"} aria-describedby={issue ? "login-error second-factor-help" : "second-factor-help"} maxLength={64} disabled={working} required />
      <p id="second-factor-help" className="text-xs leading-6 text-muted-foreground">{method === "authenticator" ? "کد ۶رقمی برنامهٔ احراز هویت را وارد کنید." : "یکی از کدهای بازیابی استفاده‌نشده را وارد کنید."}</p>
    </div>
    <button type="button" disabled={working} className="text-sm text-primary underline underline-offset-4 disabled:opacity-50" onClick={() => { setMethod(value => value === "authenticator" ? "recovery" : "authenticator"); setIssue(null); }}>{method === "authenticator" ? "استفاده از کد بازیابی" : "استفاده از برنامهٔ احراز هویت"}</button>
    </>}
    <CaptchaChallenge ref={captchaRef} config={captcha} />
    <Button type="submit" size="lg" className="w-full" disabled={working || captcha.provider === "unavailable"}>{working ? <ActivityIndicator onPrimary announce={false} state="connecting" label={phase === "security" ? "در حال بررسی…" : "در حال ورود…"} /> : step === "credentials" ? "ادامه" : "ورود"}</Button>
    {step === "mfa" ? <Button type="button" variant="ghost" className="w-full" disabled={working} onClick={() => restart()}>بازگشت به ورود</Button> : null}
    <span role="status" className="sr-only">{working ? (phase === "security" ? "در حال بررسی…" : "در حال ورود…") : ""}</span>
  </form>;
}
