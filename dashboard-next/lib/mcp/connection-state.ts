/** Receipt identity survives refresh; absent data never resolves an unknown write. */
export interface ConnectionRequest {
  id: string;
  action: "confirm" | "revoke";
  expectedVersion: number;
  storeIds: readonly string[];
  scopes: readonly string[];
}
export interface ConnectionMutation {
  request: ConnectionRequest;
  status: "sending" | "unknown" | "confirmed";
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const object = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;

function sameValues(value: unknown, expected: readonly string[]): boolean {
  return Array.isArray(value) && value.every((item) => typeof item === "string") &&
    new Set(value).size === value.length &&
    JSON.stringify([...value].sort()) === JSON.stringify([...expected].sort());
}

/** A 2xx response alone never establishes consent or completed withdrawal. */
export function connectionReceipt(request: ConnectionRequest, value: unknown): boolean {
  const row = object(value);
  if (!row || row.id !== request.id || !Number.isSafeInteger(row.version) ||
      (row.version as number) <= request.expectedVersion) return false;
  if (request.action === "revoke") return row.revoked === true;
  return row.revoked === false && sameValues(row.store_ids, request.storeIds) &&
    sameValues(row.scopes, request.scopes) && typeof row.expires_at === "string" &&
    Date.parse(row.expires_at) > Date.now();
}

/** Refresh may settle only a matching authoritative receipt. */
export function reconcileConnection(state: ConnectionMutation, receipt: unknown): ConnectionMutation {
  return connectionReceipt(state.request, receipt)
    ? { ...state, status: "confirmed" } : state;
}

/** The configured gateway issuer is a navigation origin, never executable input. */
export function gatewayDashboardUrl(issuer: string, workspace: string): string | null {
  try {
    const base = new URL(issuer);
    if (base.protocol !== "https:" || base.username || base.password || !uuid.test(workspace)) return null;
    const url = new URL("/dashboard", base);
    url.searchParams.set("workspace", workspace);
    return url.href;
  } catch { return null; }
}
