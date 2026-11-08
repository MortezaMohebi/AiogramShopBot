"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { registerWorkflowGuard } from "@/lib/workflows/navigation";
import { canonical, documentOf, mergeSave } from "@/lib/workflows/state";
import {
  WorkflowError,
  errorText,
  workflowRequest,
} from "@/lib/workflows/client";
import type { DraftDocument, WorkflowRecord } from "@/lib/workflows/types";
type SaveState = "idle" | "saving" | "unknown" | "conflict" | "error";
interface Pending {
  operation_id: string;
  expected_revision: number;
  submitted: DraftDocument;
  payload: Record<string, unknown>;
}
/** A single mutation may be in flight. Unknown outcomes are reconciled read-only. */
export function useDraftSave(
  initial: WorkflowRecord,
  document: DraftDocument,
  replace: (d: DraftDocument) => void,
) {
  const [record, setRecord] = useState(initial),
    [saved, setSaved] = useState(canonical(documentOf(initial))),
    [status, setStatus] = useState<SaveState>("idle"),
    [error, setError] = useState("");
  const latest = useRef(document),
    pending = useRef<Pending | null>(null),
    busy = useRef(false),
    replaceRef = useRef(replace);
  useEffect(() => {
    latest.current = document;
    replaceRef.current = replace;
  }, [document, replace]);
  const dirty = canonical(document) !== saved;
  const accept = useCallback(
    (response: WorkflowRecord, submitted: DraftDocument) => {
      const merged = mergeSave(latest.current, submitted, response);
      if (canonical(latest.current) === canonical(submitted))
        replaceRef.current(merged.document);
      setRecord(response);
      setSaved(merged.savedFingerprint);
      pending.current = null;
      setStatus(merged.concurrent ? "conflict" : "idle");
      setError(
        merged.concurrent
          ? "عملیات ثبت شد، اما نسخهٔ جدیدتری در سرور وجود دارد. ویرایش محلی حفظ شد."
          : "",
      );
    },
    [],
  );
  const reconcile = useCallback(async () => {
    const p = pending.current;
    if (!p || busy.current) return;
    busy.current = true;
    setStatus("saving");
    try {
      const response = await workflowRequest<WorkflowRecord>(
        `/${initial.id}/operations/${p.operation_id}`,
      );
      accept(response, p.submitted);
    } catch (e) {
      setStatus(
        e instanceof WorkflowError && e.status === 409 ? "conflict" : "unknown",
      );
      setError(
        e instanceof WorkflowError && e.status === 404
          ? "هنوز رسیدی یافت نشد. پیش از تکرار، وضعیت را دوباره بررسی کنید؛ تکرار فقط با همان شناسه انجام می‌شود."
          : errorText(e),
      );
    } finally {
      busy.current = false;
    }
  }, [accept, initial.id]);
  const submit = useCallback(
    async (retry = false) => {
      if (busy.current || !record.can_write || record.status !== "draft")
        return;
      let p = pending.current;
      if (p && !retry) return;
      if (!p) {
        const submitted = documentOf(latest.current);
        p = {
          operation_id: crypto.randomUUID(),
          expected_revision: record.revision,
          submitted,
          payload: {
            operation_id: "",
            expected_revision: record.revision,
            ...submitted,
          },
        };
        p.payload.operation_id = p.operation_id;
        pending.current = p;
      }
      busy.current = true;
      setStatus("saving");
      setError("");
      try {
        const response = await workflowRequest<WorkflowRecord>(
          `/${initial.id}`,
          "PATCH",
          p.payload,
        );
        accept(response, p.submitted);
      } catch (e) {
        if (e instanceof WorkflowError && e.status >= 400 && e.status < 500) {
          pending.current = null;
          setStatus(e.status === 409 ? "conflict" : "error");
          setError(errorText(e));
        } else {
          setStatus("unknown");
          setError(errorText(e));
        }
      } finally {
        busy.current = false;
      }
    },
    [accept, initial.id, record.can_write, record.revision, record.status],
  );
  useEffect(() => {
    if (
      !dirty ||
      status !== "idle" ||
      !record.can_write ||
      record.status !== "draft"
    )
      return;
    const timer = setTimeout(() => void submit(), 1500);
    return () => clearTimeout(timer);
  }, [document, dirty, status, record.can_write, record.status, submit]);
  const loadRemote = async () => {
    if (busy.current || pending.current) return;
    busy.current = true;
    try {
      const remote = await workflowRequest<WorkflowRecord>(`/${initial.id}`);
      replaceRef.current(documentOf(remote));
      setRecord(remote);
      setSaved(canonical(documentOf(remote)));
      setStatus("idle");
      setError("");
    } catch (e) {
      setError(errorText(e));
    } finally {
      busy.current = false;
    }
  };
  useEffect(
    () => registerWorkflowGuard(() => dirty || pending.current !== null),
    [dirty],
  );
  return {
    record,
    dirty,
    status,
    error,
    save: () => submit(),
    retry: () => submit(true),
    reconcile,
    loadRemote,
    pending: status === "unknown" || status === "saving",
  };
}
