"use client";

import { useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { controlAction } from "@/lib/account-control";

export function ReauthenticationForm({ onCancel, onVerified, onBusyChange, title, description }: {
  onCancel: () => void;
  onVerified: (password: string) => void | Promise<void>;
  onBusyChange?: (busy: boolean) => void;
  title?: string;
  description?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (busy) return;
    const form = event.currentTarget;
    const password = String(new FormData(form).get("current_password") ?? "");
    setBusy(true);
    onBusyChange?.(true);
    setError("");
    try {
      await controlAction("reauthenticate", { current_password: password });
      form.reset();
      await onVerified(password);
    } catch (issue) {
      form.reset();
      setError(issue instanceof Error ? issue.message : "تأیید هویت انجام نشد.");
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }

  return <form method="post" onSubmit={submit} className="space-y-4" aria-busy={busy}>
    <h2 className="text-lg font-semibold">{title ?? "تأیید دوبارهٔ هویت"}</h2>
    {description && <p className="text-sm leading-7 text-muted-foreground">{description}</p>}
    <label className="block space-y-2 text-sm">رمز فعلی
      <Input name="current_password" type="password" autoComplete="current-password" dir="ltr"
        maxLength={256} required disabled={busy} />
    </label>
    {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" disabled={busy}>{busy ? "در حال تأیید…" : "تأیید و ادامه"}</Button>
      <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>انصراف</Button>
    </div>
  </form>;
}

export function ReauthenticateButton({ onVerified }: { onVerified?: () => void | Promise<void> } = {}) {
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
        return onVerified?.();
      }} /></div>
    </Dialog>, document.body) : null}
  </>;
}
