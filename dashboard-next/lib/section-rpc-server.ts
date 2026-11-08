import "server-only";
import { ApiError } from "@/lib/bridge";
import type { SectionRpcError } from "@/lib/section-rpc";

export function sectionRpcError(error: unknown, command = false): SectionRpcError {
  if (error instanceof ApiError) {
    if (error.status === 401) return "session_expired";
    if (error.code === "reauthentication_required" || error.code === "store_switch_required") return error.code;
    if (error.status === 403 || error.status === 404 || error.status === 428) return "permission_denied";
    if (error.status === 409) return "conflict";
    if (error.status === 400 || error.status === 422) return "validation";
  }
  return command ? "outcome_unknown" : "unavailable";
}
