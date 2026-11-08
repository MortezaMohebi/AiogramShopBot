export type SectionRpcError =
  | "validation" | "session_expired" | "permission_denied" | "store_switch_required"
  | "reauthentication_required" | "conflict" | "unavailable" | "outcome_unknown";

export type SectionRpcResult<T> =
  | { ok: true; data: T }
  | { ok: false; code: SectionRpcError };

const errors = new Set<string>([
  "validation", "session_expired", "permission_denied", "store_switch_required", "reauthentication_required",
  "conflict", "unavailable", "outcome_unknown",
]);

/** Read one private section without starting an App Router navigation. */
export async function readSectionRpc<T>(path: string, signal?: AbortSignal): Promise<SectionRpcResult<T>> {
  try {
    const response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { Accept: "application/json" },
      signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000),
    });
    const result = await response.json() as SectionRpcResult<T> | null;
    if (response.ok && result?.ok === true && "data" in result) return result;
    if (!response.ok && result?.ok === false && errors.has(result.code)) return result;
  } catch {
    // A failed or malformed read can be requested again.
  }
  return { ok: false, code: "unavailable" };
}
