"use client";

import { useLayoutEffect, useRef, useState, useSyncExternalStore, useTransition, type FormEvent, type ReactNode } from "react";
import { ReauthenticateButton } from "@/components/blocks/reauthentication";
import { useDraftNavigation } from "@/components/blocks/use-draft-navigation";
import { DraftActions } from "@/components/ui/draft-actions";
import type { SectionRpcError, SectionRpcResult } from "@/lib/section-rpc";
import { cn } from "@/lib/utils";

export type DraftReceipt = SectionRpcResult<null> | { ok: false; message: string; requestId?: string };

const errors: Record<SectionRpcError, string> = {
  validation: "مقادیر واردشده را بررسی کنید.",
  session_expired: "نشست پایان یافته است. پس از ورود دوباره تلاش کنید.",
  permission_denied: "حساب شما مجوز ذخیرهٔ این تغییرات را ندارد.",
  store_switch_required: "فروشگاه مربوط به این فرم را انتخاب کنید.",
  reauthentication_required: "هویت خود را دوباره تأیید کنید و ذخیره را بزنید.",
  conflict: "این رکورد تغییر کرده است. صفحه را دوباره باز کنید و تغییرات را بررسی کنید.",
  unavailable: "سرویس در دسترس نیست. کمی بعد دوباره تلاش کنید.",
  outcome_unknown: "ذخیره تأیید نشد. پیش از تلاش دوباره، وضعیت رکورد را بررسی کنید.",
};

function editableSnapshot(form: HTMLFormElement, data = new FormData(form)) {
  const fields = new Set(Array.from(form.elements).filter(element =>
    element.matches("select, textarea, input:not([type=hidden]), input[data-draft-field]")
  ).map(element => (element as HTMLInputElement).name));
  const values = [...data].filter(([name]) => fields.has(name));
  const badInputs = Array.from(form.elements).filter(element =>
    element instanceof HTMLInputElement && element.validity.badInput
  ).map(element => (element as HTMLInputElement).name);
  return JSON.stringify([values, badInputs]);
}

const revisionFields = ["version", "expected_version"];
const subscribeToHydration = () => () => {};
const clientSnapshot = () => true;
const serverSnapshot = () => false;

/** Save ordinary edits before leaving and reset fields from the confirmed record. */
export function DraftForm({
  children, saveAction, className, footerClassName, autosave = true, conflictMessage,
}: {
  children: ReactNode;
  saveAction: (data: FormData) => Promise<DraftReceipt>;
  className?: string;
  footerClassName?: string;
  autosave?: boolean;
  conflictMessage?: string;
}) {
  const form = useRef<HTMLFormElement>(null);
  const baseline = useRef("");
  const capturedRevision = useRef(-1);
  const versions = useRef<FormData | null>(null);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const needsReview = useRef(false);
  const restoreFocus = useRef(false);
  const [revision, setRevision] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [pending, setPending] = useState(false);
  const [receipt, setReceipt] = useState<DraftReceipt | null>(null);
  const [committing, startTransition] = useTransition();
  const ready = useSyncExternalStore(subscribeToHydration, clientSnapshot, serverSnapshot);
  const busy = pending || committing;

  useLayoutEffect(() => {
    if (!ready || busy || !form.current) return;
    inFlight.current = null;
    if (capturedRevision.current === revision) return;
    baseline.current = editableSnapshot(form.current);
    capturedRevision.current = revision;
    if (restoreFocus.current) {
      restoreFocus.current = false;
      form.current.querySelector<HTMLElement>("input:not([type=hidden]), select, textarea, button")?.focus({ preventScroll: true });
    }
  }, [busy, ready, revision]);

  function changed(event: FormEvent<HTMLFormElement>) {
    const current = event.currentTarget;
    if (!(event.target instanceof Element) || !current.contains(event.target) || inFlight.current || committing) return;
    const data = new FormData(current);
    const differs = editableSnapshot(current, data) !== baseline.current;
    versions.current = differs ? versions.current ?? data : null;
    setDirty(differs);
    if (!needsReview.current) setReceipt(null);
  }

  function reset() {
    versions.current = null;
    needsReview.current = false;
    setDirty(false);
    setRevision(current => current + 1);
  }

  function save(automatic = false): Promise<boolean> {
    if (inFlight.current) return inFlight.current;
    const current = form.current;
    if (!current) return Promise.resolve(true);
    const data = new FormData(current);
    if (editableSnapshot(current, data) === baseline.current) return Promise.resolve(true);
    if (automatic && needsReview.current) return Promise.resolve(false);
    const disclosure = current.closest("details");
    if (!current.checkValidity()) {
      if (disclosure) disclosure.open = true;
      current.reportValidity();
      return Promise.resolve(false);
    }
    for (const name of revisionFields) {
      const version = versions.current?.get(name);
      if (version !== undefined && version !== null) data.set(name, version);
    }

    setPending(true);
    setReceipt(null);
    const command = new Promise<boolean>(resolve => {
      startTransition(async () => {
        let result: DraftReceipt;
        try {
          result = await Promise.resolve().then(() => saveAction(data));
        } catch {
          result = { ok: false, code: "outcome_unknown" };
        }
        // Apply defaults together with the Server Action's revalidated page.
        startTransition(() => {
          needsReview.current = !result.ok && ("message" in result ||
            result.code === "outcome_unknown" || result.code === "reauthentication_required");
          if (result.ok) reset();
          else if (disclosure) disclosure.open = true;
          setReceipt(result);
          setPending(false);
        });
        resolve(result.ok);
      });
    });
    inFlight.current = command;
    return command;
  }

  useDraftNavigation(autosave && (dirty || pending), () => save(true));
  const error = receipt && !receipt.ok
    ? ("message" in receipt ? receipt.message : receipt.code === "conflict" && conflictMessage || errors[receipt.code])
    : null;

  return <form ref={form} method="post" aria-busy={!ready || busy}
    onInput={changed} onChange={changed}
    onSubmit={event => {
      if (event.target !== event.currentTarget) return;
      event.preventDefault();
      void save();
    }}>
    <fieldset key={revision} className={cn("min-w-0", className)} disabled={!ready || busy}>
      {children}
      {dirty || busy || receipt ? <div className={footerClassName}>
        <DraftActions dirty={dirty} pending={busy} submit
          onDiscard={() => {
            restoreFocus.current = true;
            reset();
            setReceipt(null);
          }} />
        {error && <p role="alert" className="mt-1 text-sm text-destructive">{error}</p>}
        {receipt && !receipt.ok && "code" in receipt && receipt.code === "reauthentication_required" && <ReauthenticateButton />}
        {receipt && "requestId" in receipt && receipt.requestId && <details className="text-xs">
          <summary>اطلاعات پیگیری</summary><p dir="ltr">{receipt.requestId}</p>
        </details>}
        {receipt?.ok && <p role="status" className="text-xs text-muted-foreground">تغییرات ذخیره شد.</p>}
      </div> : null}
    </fieldset>
  </form>;
}
