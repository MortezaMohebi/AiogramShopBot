import "server-only";
import { adminFetch, ApiError } from "@/lib/bridge";

/** Only known upstream service errors become a local, non-empty section failure. */
export async function readSection<T>(path: string): Promise<{ ok: true; data: T } | { ok: false }> {
  try {
    return { ok: true, data: await adminFetch<T>(path) };
  } catch (error) {
    // Preserve auth redirects, forbidden/conflict responses and programming errors.
    if (error instanceof ApiError && error.status >= 500 && error.status < 600) return { ok: false };
    throw error;
  }
}
