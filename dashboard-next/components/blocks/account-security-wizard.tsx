"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { ControlActionError, controlAction } from "@/lib/account-control";

export const securityActions = {
  username: "تغییر نام کاربری",
  password: "تغییر رمز عبور",
  "mfa-setup": "فعال‌سازی احراز هویت دومرحله‌ای",
  "mfa-disable": "غیرفعال‌سازی احراز هویت دومرحله‌ای",
} as const;

export type SecurityAction = keyof typeof securityActions;
type Step =
  | { name: "proof" }
  | { name: "operation"; token: string }
  | { name: "enrollment" }
  | { name: "sign-in" }
  | { name: "authenticator"; secret: string; qr: string }
  | { name: "recovery"; codes: string[] };

export function AccountSecurityWizard({
  action, reuseLoginProof, minimumPassword, onClose, onSuccess,
}: {
  action: SecurityAction;
  reuseLoginProof: boolean;
  minimumPassword: number;
  onClose: () => void;
  onSuccess: (message: string) => void;
}) {
  const router = useRouter();
  const heading = useRef<HTMLHeadingElement>(null);
  const firstStep: Step = action === "mfa-setup" && reuseLoginProof
    ? { name: "enrollment" }
    : { name: "proof" };
  const [step, setStep] = useState<Step>(firstStep);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const title = {
    proof: "تأیید رمز فعلی",
    operation: securityActions[action],
    enrollment: securityActions["mfa-setup"],
    "sign-in": "تأیید دوبارهٔ ورود",
    authenticator: "اتصال برنامهٔ احراز هویت",
    recovery: "ذخیرهٔ کدهای بازیابی",
  }[step.name];
  useEffect(() => { heading.current?.focus(); }, [step.name]);

  function finish(message: string) {
    onSuccess(message);
    onClose();
    router.refresh();
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || step.name === "recovery" || step.name === "sign-in") return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const get = (field: string) => String(fields.get(field) ?? "");
    if (step.name === "operation" && action === "password"
      && get("new_password") !== get("confirm_password")) {
      setError("رمز تازه و تکرار آن یکسان نیستند.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (step.name === "proof") {
        const result = await controlAction("verify-password", {
          action, current_password: get("current_password"),
        });
        if (!result.proof_token) throw new Error("تأیید رمز کامل نشد. دوباره تلاش کنید.");
        form.reset();
        setStep({ name: "operation", token: result.proof_token });
        return;
      }
      if (step.name === "authenticator") {
        const code = get("code").replace(/[۰-۹٠-٩]/g, char =>
          String("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩".indexOf(char) % 10)).trim();
        const result = await controlAction("mfa-confirm", { code });
        if (!result.recovery_codes?.length) throw new Error("کدهای بازیابی دریافت نشدند. وضعیت حساب را بررسی کنید.");
        form.reset();
        setStep({ name: "recovery", codes: result.recovery_codes });
        return;
      }
      const result = await controlAction(action, step.name === "enrollment" ? {} : {
        proof_token: step.token,
        ...(action === "username" ? { username: get("username").trim().toLowerCase() } : {}),
        ...(action === "password" ? { new_password: get("new_password") } : {}),
        ...(action === "mfa-disable" ? { second_factor: get("second_factor").trim() } : {}),
      });
      form.reset();
      if (result.login_required) {
        window.location.replace("/login");
      } else if (action === "mfa-setup") {
        if (!result.secret || !result.qr_data_uri?.startsWith("data:image/png;base64,")) {
          throw new Error("کد QR دریافت نشد. دوباره فعال‌سازی را شروع کنید.");
        }
        setStep({ name: "authenticator", secret: result.secret, qr: result.qr_data_uri });
      } else {
        finish("احراز هویت دومرحله‌ای غیرفعال شد.");
      }
    } catch (issue) {
      if (issue instanceof ControlActionError) {
        if (firstStep.name === "enrollment" && ["reauthentication_required", "session_expired"].includes(issue.code)) {
          setStep({ name: "sign-in" });
          return;
        }
        if (["account_proof_expired", "mfa_enrollment_expired"].includes(issue.code)) {
          form.reset();
          setStep(firstStep);
        }
      }
      setError(issue instanceof Error ? issue.message : "عملیات انجام نشد.");
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open label={title} onClose={() => {
    if (!busy && step.name !== "recovery") onClose();
  }}>
    <section className="space-y-5 p-5 sm:p-6">
      <h2 ref={heading} tabIndex={-1} className="text-lg font-semibold">{title}</h2>
      {step.name === "recovery" ? <>
        <p className="text-sm leading-7">احراز هویت دومرحله‌ای فعال شد. کدها را در جای امن ذخیره کنید. هر کد یک‌بار قابل استفاده است و پس از بستن این مرحله دوباره نمایش داده نمی‌شود.</p>
        <pre dir="ltr" className="overflow-x-auto rounded-lg border bg-muted p-3 text-xs leading-6">{step.codes.join("\n")}</pre>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={async () => {
            try { await navigator.clipboard.writeText(step.codes.join("\n")); setCopied(true); }
            catch { setError("کپی خودکار انجام نشد. کدها را انتخاب و دستی کپی کنید."); }
          }}>کپی کدها</Button>
          <Button type="button" onClick={() => finish("احراز هویت دومرحله‌ای فعال شد.")}>کدها را ذخیره کردم</Button>
        </div>
        {copied ? <p role="status" className="text-sm">کدها کپی شدند.</p> : null}
      </> : step.name === "sign-in" ? <>
        <p role="alert" className="text-sm text-muted-foreground">زمان تأیید ورود پایان یافته است. دوباره وارد شوید و فعال‌سازی را ادامه دهید.</p>
        <div className="flex flex-wrap gap-2">
          <Button asChild><Link href="/login">ورود دوباره</Link></Button>
          <Button type="button" variant="outline" onClick={onClose}>انصراف</Button>
        </div>
      </> : <form key={step.name} method="post" onSubmit={submit} className="space-y-4" aria-busy={busy}>
        {step.name === "proof" ? <>
          <p className="text-sm text-muted-foreground">برای «{securityActions[action]}»، رمز فعلی حساب را وارد کنید.</p>
          <label className="block space-y-2 text-sm">رمز فعلی
            <Input name="current_password" type="password" autoComplete="current-password"
              maxLength={256} dir="ltr" required disabled={busy} />
          </label>
        </> : step.name === "authenticator" ? <>
          <p className="text-sm leading-7">QR را با برنامهٔ Authenticator اسکن کنید و کد شش‌رقمی برنامه را وارد کنید.</p>
          <div className="mx-auto w-fit rounded-lg bg-white p-3">
            <Image src={step.qr} alt="QR فعال‌سازی احراز هویت دومرحله‌ای" width={200} height={200}
              unoptimized className="h-auto max-w-full" />
          </div>
          <details className="rounded-lg border p-3 text-sm">
            <summary className="cursor-pointer">نمایش کلید برای ورود دستی</summary>
            <p className="mt-2 text-muted-foreground">کلید محرمانه است. آن را به اشتراک نگذارید.</p>
            <code dir="ltr" className="mt-2 block select-all break-all">{step.secret}</code>
          </details>
          <label className="block space-y-2 text-sm">کد شش‌رقمی برنامه
            <Input name="code" dir="ltr" inputMode="numeric" autoComplete="one-time-code"
              minLength={6} maxLength={6} spellCheck={false} required disabled={busy} />
          </label>
        </> : <>
          {action === "username" ? <label className="block space-y-2 text-sm">نام کاربری جدید
            <Input name="username" dir="ltr" minLength={3} maxLength={80} spellCheck={false}
              autoComplete="username" autoCapitalize="none" required disabled={busy} />
          </label> : null}
          {action === "password" ? <div className="space-y-3">
            <label className="block space-y-2 text-sm">رمز تازه (حداقل {minimumPassword.toLocaleString("fa-IR")} نویسه)
              <Input name="new_password" type="password" autoComplete="new-password"
                minLength={minimumPassword} maxLength={256} dir="ltr" required disabled={busy} />
            </label>
            <label className="block space-y-2 text-sm">تکرار رمز تازه
              <Input name="confirm_password" type="password" autoComplete="new-password"
                minLength={minimumPassword} maxLength={256} dir="ltr" required disabled={busy} />
            </label>
          </div> : null}
          {action === "username" || action === "password" ? <p className="text-sm text-muted-foreground">پس از ثبت، از همهٔ دستگاه‌ها خارج می‌شوید و باید دوباره وارد شوید.</p> : null}
          {action === "mfa-setup" ? <p className="text-sm text-muted-foreground">برنامهٔ Authenticator را آماده کنید. در مرحلهٔ بعد QR نمایش داده می‌شود.</p> : null}
          {action === "mfa-disable" ? <label className="block space-y-2 text-sm">کد برنامه یا کد بازیابی
            <Input name="second_factor" dir="ltr" autoComplete="one-time-code" maxLength={64}
              spellCheck={false} required disabled={busy} />
          </label> : null}
        </>}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={busy}>{busy ? "در حال بررسی…" : step.name === "proof" ? "تأیید رمز و ادامه"
            : step.name === "authenticator" ? "تأیید و فعال‌سازی"
            : action === "mfa-setup" ? "نمایش QR" : "ثبت تغییر"}</Button>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>انصراف</Button>
        </div>
      </form>}
      {error ? <p role="alert" className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">{error}</p> : null}
    </section>
  </Dialog>;
}
