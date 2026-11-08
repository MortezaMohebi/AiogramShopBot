"use client";

import { useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { controlAction } from "@/lib/account-control";

export function ReauthenticationForm({ onCancel, onVerified, onBusyChange }: {
  onCancel: () => void;
  onVerified: () => void | Promise<void>;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const secondFactor = String(fields.get("second_factor") ?? "").trim()
      .replace(/[۰-۹٠-٩]/g, digit => String("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩".indexOf(digit) % 10));
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    try {
      await controlAction("reauthenticate", {
        current_password: String(fields.get("current_password") ?? ""),
        second_factor: secondFactor,
      });
      form.reset();
      await onVerified();
    } catch (issue) {
      form.reset();
      setError(issue instanceof Error ? issue.message : "تأیید هویت انجام نشد.");
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }

  return <form method="post" onSubmit={submit} className="space-y-4" aria-busy={busy}>
    <h2 className="text-lg font-semibold">تأیید دوبارهٔ هویت</h2>
    <p className="text-sm leading-7 text-muted-foreground">تأیید هویت در این نشست پنج دقیقه اعتبار دارد.</p>
    <label className="block space-y-2 text-sm">رمز فعلی
      <Input name="current_password" type="password" autoComplete="current-password" dir="ltr"
        maxLength={256} required disabled={busy} />
    </label>
    <label className="block space-y-2 text-sm">کد احراز هویت دومرحله‌ای یا کد بازیابی
      <Input name="second_factor" autoComplete="one-time-code" dir="ltr" maxLength={64}
        spellCheck={false} disabled={busy} />
    </label>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" disabled={busy}>{busy ? "در حال تأیید…" : "تأیید و ادامه"}</Button>
      <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>انصراف</Button>
    </div>
  </form>;
}

export function ReauthenticateButton({ onVerified }: { onVerified?: () => void } = {}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  return <>
    <Button type="button" size="sm" variant="outline" onClick={() => {
      setConfirmed(false);
      setOpen(true);
    }}>تأیید هویت</Button>
    {confirmed ? <span role="status" className="text-sm">هویت تأیید شد.</span> : null}
    {open ? createPortal(<Dialog open label="تأیید دوبارهٔ هویت" onClose={() => { if (!busy) setOpen(false); }}>
      <div className="p-5"><ReauthenticationForm onBusyChange={setBusy} onCancel={() => setOpen(false)} onVerified={() => {
        setOpen(false);
        setConfirmed(true);
        onVerified?.();
      }} /></div>
    </Dialog>, document.body) : null}
  </>;
}
