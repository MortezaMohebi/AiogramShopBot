import "server-only";
import { notFound } from "next/navigation";
import { adminFetch, ApiError } from "@/lib/bridge";
import type { WorkflowRecord } from "./types";
/** Preserve signed API authorization; only a true missing scoped record becomes 404. */
export async function workflowRecord(id: string): Promise<WorkflowRecord> {
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  try {
    return await adminFetch<WorkflowRecord>(`/workflows/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
