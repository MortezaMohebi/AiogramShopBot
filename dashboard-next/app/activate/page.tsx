"use client";

import Link from "next/link";
import { useState, useSyncExternalStore, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { requestBrowserChallenge } from "@/lib/browser-challenge";

import { createActivationStore } from "@/lib/activation-fragment";

/** Read the raw capability from a URL fragment, never a server-visible query. */
export default function ActivateAccountPage() {
  const router = useRouter();
  const [activation] = useState(createActivationStore);
  const claim = useSyncExternalStore(
    activation.subscribe, activation.getSnapshot, activation.getServerSnapshot,
  );
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [completed, setCompleted] = useState(false);



  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (working || !claim) return;
    const data = new FormData(event.currentTarget);
    const password = String(data.get("password") ?? "");
    const confirmation = String(data.get("confirmation") ?? "");
    if (password !== confirmation) { setMessage("تکرار رمز عبور یکسان نیست."); return; }
    if (password.length < 12 || password.length > 256) { setMessage("طول رمز عبور معتبر نیست."); return; }
    setWorking(true); setMessage(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/auth/redeem", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        redirect: "error", headers: {
          "Content-Type": "application/json", Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ ...claim, password }),
        signal: AbortSignal.timeout(30_000),
      });
      const result = await response.json() as { ok?: boolean; code?: string };
      if (!response.ok || result.ok !== true) {
        const code = result.code;
        setMessage(code === "invalid_link"
          ? "این لینک منقضی شده، لغو شده یا قبلاً استفاده شده است."
          : code === "password_policy_failed"
            ? "رمز انتخابی با سیاست فعلی سازمان مطابقت ندارد؛ رمز قوی‌تری انتخاب کنید."
            : code === "temporarily_locked"
              ? "تلاش‌های زیادی ثبت شده است؛ بعداً دوباره امتحان کنید."
              : "ثبت حساب انجام نشد. وضعیت اتصال و لینک را بررسی کنید.");
        return;
      }
      setCompleted(true);
      activation.clear();
      setMessage("رمز حساب تنظیم شد؛ اکنون وارد شوید.");
    } catch {
      setMessage("اتصال به سرویس برقرار نشد؛ بدون ارسال دوبارهٔ خودکار، وضعیت را بررسی کنید.");
    } finally { setWorking(false); }
  }

  return <main className="grid min-h-screen place-items-center px-4 py-10" dir="rtl">
    <Card className="w-full max-w-lg">
      <CardHeader><CardTitle className="flex items-center gap-2">
        <KeyRound className="size-5" /> {claim?.kind === "reset" ? "بازیابی رمز عبور" : "پذیرش دعوت‌نامهٔ کارکنان"}
      </CardTitle></CardHeader>
      <CardContent className="space-y-5">
        {message ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm leading-7">{message}</p> : null}
        {completed ? <Button type="button" onClick={() => router.replace("/login")}>رفتن به صفحهٔ ورود</Button>
          : claim ? <form onSubmit={submit} className="space-y-4" aria-busy={working}>
            <p className="text-sm leading-7 text-muted-foreground">رمز عبور باید بین ۱۲ تا ۲۵۶ نویسه باشد.</p>
            <label className="block space-y-2 text-sm">رمز جدید
              <Input name="password" type="password" autoComplete="new-password" minLength={12} maxLength={256} dir="ltr" disabled={working} required />
            </label>
            <label className="block space-y-2 text-sm">تکرار رمز جدید
              <Input name="confirmation" type="password" autoComplete="new-password" minLength={12} maxLength={256} dir="ltr" disabled={working} required />
            </label>
            <Button type="submit" disabled={working}>{working ? "در حال بررسی…" : "ذخیرهٔ رمز عبور"}</Button>
          </form> : <p role="alert" className="text-sm leading-7 text-destructive">لینک معتبر یافت نشد. برای دریافت لینک جدید با مدیر تماس بگیرید.</p>}
        <Link href="/login" className="inline-block text-sm underline underline-offset-4">بازگشت به ورود</Link>
      </CardContent>
    </Card>
  </main>;
}
