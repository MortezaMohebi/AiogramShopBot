"use client";
import { useEffect, useRef, useState } from "react";
import {
  WorkflowError,
  errorText,
  workflowRequest,
} from "@/lib/workflows/client";
import { registerWorkflowGuard } from "@/lib/workflows/navigation";
import type { WorkflowRecord } from "@/lib/workflows/types";
interface Mutation {
  path: string;
  method: "POST" | "DELETE";
  targetId: string;
  payload: { operation_id: string; [key: string]: unknown };
}
/** Retain exact request identity across uncertain create/restore/archive outcomes. */
export function useWorkflowOperation(
  onSuccess: (record: WorkflowRecord) => void,
) {
  const [status, setStatus] = useState<"idle" | "busy" | "unknown" | "error">(
      "idle",
    ),
    [error, setError] = useState("");
  const pending = useRef<Mutation | null>(null),
    busy = useRef(false);
  useEffect(
    () =>
      registerWorkflowGuard(() => status === "busy" || status === "unknown"),
    [status],
  );
  const accept = (record: WorkflowRecord) => {
    pending.current = null;
    setStatus("idle");
    setError("");
    onSuccess(record);
  };
  const execute = async (mutation?: Mutation) => {
    if (busy.current || (!mutation && !pending.current)) return;
    if (mutation && pending.current) return;
    const op = mutation ?? pending.current!;
    pending.current = op;
    busy.current = true;
    setStatus("busy");
    setError("");
    try {
      accept(
        await workflowRequest<WorkflowRecord>(op.path, op.method, op.payload),
      );
    } catch (e) {
      if (e instanceof WorkflowError && e.status >= 400 && e.status < 500) {
        pending.current = null;
        setStatus("error");
      } else setStatus("unknown");
      setError(errorText(e));
    } finally {
      busy.current = false;
    }
  };
  const reconcile = async () => {
    const op = pending.current;
    if (!op || busy.current) return;
    busy.current = true;
    setStatus("busy");
    try {
      accept(
        await workflowRequest<WorkflowRecord>(
          `/${op.targetId}/operations/${op.payload.operation_id}`,
        ),
      );
    } catch (e) {
      setStatus("unknown");
      setError(
        e instanceof WorkflowError && e.status === 404
          ? "رسید عملیات هنوز پیدا نشد. دوباره بررسی کنید یا همان عملیات را تکرار کنید."
          : errorText(e),
      );
    } finally {
      busy.current = false;
    }
  };
  return {
    status,
    error,
    run: (op: Mutation) => execute(op),
    retry: () => execute(),
    reconcile,
  };
}
export function OperationNotice({
  operation,
}: {
  operation: ReturnType<typeof useWorkflowOperation>;
}) {
  return operation.error ? (
    <div
      role="alert"
      className="space-y-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-sm leading-7"
    >
      <p className="break-words">{operation.error}</p>
      {operation.status === "unknown" && (
        <div className="flex flex-wrap gap-2">
          <button
            className="rounded border px-3 py-2"
            type="button"
            onClick={() => void operation.reconcile()}
          >
            بررسی رسید عملیات
          </button>
          <button
            className="rounded border px-3 py-2"
            type="button"
            onClick={() => void operation.retry()}
          >
            تکرار همان عملیات
          </button>
        </div>
      )}
    </div>
  ) : null;
}
