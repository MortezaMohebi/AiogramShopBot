"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { runtimeRequest, RuntimeError, runtimeErrorText } from "@/lib/runtime/client";
import { createRuntimeIntent, runtimeAuditMatches, type RuntimeMutationContext, type RuntimeMutationIntent } from "@/lib/runtime/receipts";
import type { HistoryItem, Page } from "@/lib/runtime/types";
interface Evidence extends RuntimeMutationContext {
  operationId?: string;
  previewId?: string;
}
/** Never replay a lost write. Read persisted audit evidence before accepting its outcome. */
export function useRuntimeMutation() {
  const router = useRouter(),
    active = useRef(true),
    inFlight = useRef(false),
    pending = useRef<RuntimeMutationIntent | null>(null);
  const [state, setState] = useState<{
    status: "idle" | "busy" | "done" | "error" | "unknown";
    message: string;
    reauth?: boolean;
    intent?: RuntimeMutationIntent;
  }>({
    status: "idle",
    message: ""
  });
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function execute(path: string, payload: unknown, message: string, evidence: Evidence = {}) {
    if (inFlight.current || pending.current || state.status === "unknown" || state.status === "done") return;
    const intent = createRuntimeIntent(path, payload, evidence);
    pending.current = intent;
    inFlight.current = true;
    setState({
      status: "busy",
      message: "در حال ثبت درخواست…",
      intent
    });
    try {
      await runtimeRequest(intent.path, "POST", intent.payload, intent.context);
      pending.current = null;
      if (active.current) {
        setState({
          status: "done",
          message,
          intent
        });
        router.refresh();
      }
    } catch (error) {
      if (active.current) {
        const uncertain = error instanceof RuntimeError && (error.status === 0 || error.status >= 500);
        if (!uncertain) pending.current = null;
        setState({
          status: uncertain ? "unknown" : "error",
          message: runtimeErrorText(error),
          reauth: error instanceof RuntimeError && error.code === "reauthentication_required",
          intent
        });
      }
    } finally {
      inFlight.current = false;
    }
  }
  async function inspect() {
    const intent = pending.current;
    if (checking || !intent || state.status !== "unknown") return;
    setChecking(true);
    try {
      const history = await runtimeRequest<Page<HistoryItem>>("/history");
      const found = history.items.some(item => runtimeAuditMatches(intent, item));
      if (active.current) {
        if (found) {
          pending.current = null;
          setState({ status: "done", message: "ثبت عملیات در تاریخچه تأیید شد.", intent });
          router.refresh();
        } else setState(old => ({
          ...old,
          message: "در آخرین صفحهٔ تاریخچه نتیجهٔ قطعی پیدا نشد. درخواست دوباره ارسال نمی‌شود؛ تاریخچه و وضعیت جاری را بررسی کنید."
        }));
      }
    } catch (error) {
      if (active.current) setState(old => ({
        ...old,
        message: runtimeErrorText(error)
      }));
    } finally {
      if (active.current) setChecking(false);
    }
  }
  return {
    state,
    execute,
    inspect,
    checking,
    disabled: state.status === "busy" || state.status === "unknown" || state.status === "done"
  };
}
export function RuntimeMutationNotice({
  mutation
}: {
  mutation: ReturnType<typeof useRuntimeMutation>;
}) {
  const {
    state
  } = mutation;
  if (state.status === "idle") return null;
  return <div role={state.status === "error" || state.status === "unknown" ? "alert" : "status"} className="space-y-3 rounded-lg border bg-muted/20 p-3 text-sm leading-7">
  <p>
    {state.message}
  </p>
  {state.reauth && <Link className="text-primary underline" href="/account" target="_blank" rel="noopener noreferrer">تأیید دوبارهٔ هویت در حساب من</Link>}
  {state.status === "unknown" && <Button type="button" variant="outline" size="sm" disabled={mutation.checking} onClick={() => void mutation.inspect()}>
    {mutation.checking ? "در حال بررسی…" : "بررسی نتیجه در تاریخچه"}
  </Button>}
</div>;
}
