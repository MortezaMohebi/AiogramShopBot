import "server-only";
import { bridgeFetch } from "@/lib/bridge";

/** Only a positive answer from the database enables the first-run form. */
export async function firstOwnerPending(): Promise<boolean | null> {
  try {
    const status = await bridgeFetch<{ pending?: unknown }>(
      "/auth/owner-setup", "GET", null, null, 3000,
    );
    return typeof status?.pending === "boolean" ? status.pending : null;
  } catch {
    return null;
  }
}
