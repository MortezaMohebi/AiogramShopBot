"use client";

import { useState, useTransition, type FormEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { isRedirectError } from "next/dist/client/components/redirect-error";
import { Dialog } from "@/components/ui/dialog";
import { ReauthenticationForm } from "@/components/blocks/reauthentication";

/** Retain the submitted fields while an administrator confirms an explicit action. */
export function PasswordActionForm({ action, children, className, title, description, includePassword = true, when = "always" }: {
  action: (fields: FormData) => Promise<void | { reauthenticate: true }>;
  children: ReactNode;
  className?: string;
  title?: string;
  description?: string;
  includePassword?: boolean;
  when?: "always" | "required";
}) {
  const [pending, setPending] = useState<FormData>();
  const [busy, setBusy] = useState(false);
  const [submitting, startTransition] = useTransition();
  const [error, setError] = useState("");

  function open(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || submitting) return;
    const fields = new FormData(event.currentTarget, (event.nativeEvent as SubmitEvent).submitter);
    setError("");
    if (when === "always") {
      setPending(fields);
      return;
    }
    startTransition(async () => {
      try {
        if ((await action(fields))?.reauthenticate) setPending(fields);
      } catch (issue) {
        if (!isRedirectError(issue)) {
          setError("پاسخ نهایی دریافت نشد. پیش از تلاش دوباره وضعیت رکورد را بررسی کنید.");
        }
      }
    });
  }

  function close() {
    if (!busy) setPending(undefined);
  }

  return <>
    <form method="post" className={className} onSubmit={open} aria-busy={submitting || busy}>
      {children}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </form>
    {pending && createPortal(<Dialog open label={title ?? "تأیید دوبارهٔ هویت"} onClose={close}>
      <div className="p-5"><ReauthenticationForm title={title} description={description}
        onCancel={close} onBusyChange={setBusy} onVerified={async password => {
          if (includePassword) pending.set("current_password", password);
          try {
            if ((await action(pending))?.reauthenticate) {
              throw new Error("تأیید هویت ثبت نشد. دوباره تلاش کنید.");
            }
            setPending(undefined);
          } catch (issue) {
            // Next already follows server-action redirects, including on the same page.
            if (!isRedirectError(issue)) throw issue;
            setPending(undefined);
          } finally {
            pending.delete("current_password");
          }
        }} /></div>
    </Dialog>, document.body)}
  </>;
}
