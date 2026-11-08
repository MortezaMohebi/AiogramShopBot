/** Validate committed Runtime evidence against the exact local request, never HTTP status alone. */
import type { HistoryItem } from "./types";

export interface RuntimeMutationContext {
  scopeKey?: string;
  revision?: number;
}
export interface RuntimeMutationIntent {
  path: string;
  payload: Readonly<Record<string, unknown>>;
  context: Readonly<RuntimeMutationContext>;
}
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const kinds = ["command", "menu", "start", "internal", "admin_test"];
const runStates = ["active", "waiting_input", "waiting_action", "waiting_approval", "waiting_timeout", "completed", "cancelled", "failed", "expired", "suspended"];
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function id(value: unknown): value is string { return typeof value === "string" && uuid.test(value); }
function sameId(left: unknown, right: unknown): boolean {
  return id(left) && id(right) && left.toLowerCase() === right.toLowerCase();
}
function integer(value: unknown, minimum = 0): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum;
}
function text(value: unknown, maximum = 128): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}
function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}
function code(value: unknown): value is string {
  return typeof value === "string" && /^[a-z][a-z0-9_]{0,100}$/.test(value);
}
function list(value: unknown, predicate: (entry: unknown) => boolean): value is unknown[] {
  return Array.isArray(value) && value.every(predicate);
}
function freeze(value: unknown): void {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
}
/** Clone before awaiting a challenge/Web Lock so later form edits cannot change pending intent. */
export function createRuntimeIntent(path: string, payload: unknown, context: RuntimeMutationContext = {}): RuntimeMutationIntent {
  const snapshot: unknown = JSON.parse(JSON.stringify(payload ?? {}));
  if (!object(snapshot)) throw new Error("runtime_invalid_request");
  const expected: RuntimeMutationContext = {};
  if (context.scopeKey !== undefined) expected.scopeKey = context.scopeKey;
  if (context.revision !== undefined) expected.revision = context.revision;
  const intent = { path, payload: snapshot, context: expected };
  freeze(intent);
  return intent;
}
function scopeKey(payload: Record<string, unknown>, context: RuntimeMutationContext): string | null {
  if (id(payload.bot_id)) {
    const expected = `bot:${payload.bot_id.toLowerCase()}`;
    return context.scopeKey === undefined || context.scopeKey.toLowerCase() === expected ? expected : null;
  }
  if (payload.bot_id === null && typeof context.scopeKey === "string" && context.scopeKey.startsWith("store:") && id(context.scopeKey.slice(6))) return context.scopeKey.toLowerCase();
  return null;
}
/** Normalize only documented BindingSpec defaults; request/response ordering carries no authority. */
function binding(value: unknown): Record<string, unknown> | null {
  if (!object(value) || !id(value.bot_id) || typeof value.kind !== "string" || !kinds.includes(value.kind) || typeof value.key !== "string" || !/^[a-z][a-z0-9_-]{0,63}$/.test(value.key) || !text(value.node_id, 64)) return null;
  const result = {
    bot_id: value.bot_id.toLowerCase(), kind: value.kind, key: value.key, node_id: value.node_id,
    priority: value.priority === undefined ? 0 : value.priority, enabled: value.enabled === undefined ? true : value.enabled,
    eligibility: value.eligibility === undefined ? "all" : value.eligibility, fallback: value.fallback === undefined ? "ignore" : value.fallback,
    version_policy: value.version_policy === undefined ? "active_publication" : value.version_policy,
  };
  return integer(result.priority) && result.priority <= 100 && typeof result.enabled === "boolean" && ["all", "existing_customer"].includes(result.eligibility as string) && ["ignore"].includes(result.fallback as string) && result.version_policy === "active_publication" ? result : null;
}
function pointer(value: unknown): value is Record<string, unknown> {
  return object(value) && id(value.id) && id(value.bot_id) && id(value.publication_id) && text(value.node_id, 64) && integer(value.version, 1) && typeof value.kind === "string" && kinds.includes(value.kind) && typeof value.key === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value.key) && typeof value.enabled === "boolean";
}
function bindingIdentity(value: Record<string, unknown>): string { return `${value.bot_id}:${value.kind}:${value.key}`; }
function pointerIdentity(value: Record<string, unknown>): string {
  return JSON.stringify([value.id, value.bot_id, value.node_id, value.version, value.publication_id, value.kind, value.key, value.enabled]);
}
function sameItems(left: unknown[], right: unknown[]): boolean {
  return JSON.stringify(left.map(item => JSON.stringify(item)).sort()) === JSON.stringify(right.map(item => JSON.stringify(item)).sort());
}
function validPreview(value: Record<string, unknown>, payload: Record<string, unknown>): boolean {
  if (!id(payload.workflow_id) || !integer(payload.revision, 1) || !Array.isArray(payload.bindings) || payload.bindings.length === 0 || !payload.bindings.every(item => binding(item) !== null)) return false;
  if (!id(value.preview_id) || !timestamp(value.expires_at) || typeof value.ready !== "boolean" || !list(value.issues, issue => object(issue) && code(issue.code) && (issue.message === undefined || typeof issue.message === "string") && (issue.node_id === undefined || issue.node_id === null || text(issue.node_id, 64)))) return false;
  if (!list(value.dependencies, entry => object(entry) && text(entry.node_id, 64) && typeof entry.key === "string" && /^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$/.test(entry.key) && typeof entry.version === "string" && /^\d+\.\d+\.\d+$/.test(entry.version) && ["none", "customer_confirmation", "operator_approval", "both"].includes(entry.confirmation as string) && ["none", "read_only", "reversible", "business_mutation", "external_mutation", "irreversible"].includes(entry.side_effect as string))) return false;
  if (!list(value.mutating_nodes, entry => text(entry, 64)) || !list(value.platforms, entry => entry === "telegram" || entry === "bale") || value.platforms.length === 0 || !object(value.diff)) return false;
  const diff = value.diff;
  if (!(diff.previous_revision === null || integer(diff.previous_revision, 1)) || diff.next_revision !== payload.revision || typeof diff.definition_changed !== "boolean" || diff.retains_unselected_bindings !== true || !list(diff.previous_bindings, pointer) || !list(diff.unchanged_bindings, pointer) || !list(diff.next_bindings, entry => binding(entry) !== null)) return false;
  const selected = payload.bindings.map(item => binding(item)!);
  if (!sameItems(selected, diff.next_bindings.map(item => binding(item)!))) return false;
  const selectedKeys = new Set(selected.map(bindingIdentity));
  // Older receipts have no comparisons. When supplied, bind every baseline to
  // precisely one selected entry and the pointer already attributed to that key.
  if (diff.binding_comparisons !== undefined) {
    if (!Array.isArray(diff.binding_comparisons) || diff.binding_comparisons.length !== selected.length) return false;
    const remaining = new Set(selectedKeys);
    const pointers = new Map(diff.previous_bindings.map(item => [bindingIdentity(item as Record<string, unknown>), item as Record<string, unknown>]));
    const revisions = new Set<number | null>();
    let changed = false;
    for (const item of diff.binding_comparisons) {
      if (!object(item) || typeof item.definition_changed !== "boolean" || !remaining.delete(bindingIdentity(item))) return false;
      const active = pointers.get(bindingIdentity(item));
      if (active ? !sameId(item.previous_publication_id, active.publication_id) || !integer(item.previous_revision, 1)
        : item.previous_publication_id !== null || item.previous_revision !== null || !item.definition_changed) return false;
      if (item.previous_revision === diff.next_revision && item.definition_changed) return false;
      revisions.add(item.previous_revision as number | null);
      changed ||= item.definition_changed;
    }
    if (remaining.size || changed !== diff.definition_changed || (revisions.size === 1 ? [...revisions][0] : null) !== diff.previous_revision) return false;
  }
  const retained = diff.previous_bindings.filter(item => !selectedKeys.has(bindingIdentity(item as Record<string, unknown>)));
  return sameItems(retained.map(item => pointerIdentity(item as Record<string, unknown>)), diff.unchanged_bindings.map(item => pointerIdentity(item as Record<string, unknown>)));
}
function safeRun(value: Record<string, unknown>, payload: Record<string, unknown>): boolean {
  return [value.store_id, value.bot_id, value.workflow_id, value.publication_id].every(id) && text(value.node_id, 64) && (value.platform === "telegram" || value.platform === "bale") && typeof value.status === "string" && runStates.includes(value.status) && integer(value.lock_version) && integer(payload.expected_version) && value.lock_version > payload.expected_version && [value.created_at, value.updated_at, value.expires_at].every(timestamp) && text(value.correlation_id) && (value.error_code === null || code(value.error_code)) && (payload.operation !== "cancel" || value.status === "cancelled") && (payload.operation !== "mark_failed" || value.status === "failed");
}
/** Only a route-specific receipt for this request can establish a committed response. */
export function validRuntimeMutationReceipt(path: string, payload: Record<string, unknown>, value: unknown, context: RuntimeMutationContext = {}): boolean {
  if (!object(value) || value.ok === false) return false;
  if (path === "/publications/preview") return validPreview(value, payload);
  if (typeof value.replayed !== "boolean") return false;
  if (path === "/publications/activate") {
    return payload.approved === true && sameId(value.preview_id, payload.preview_id) && id(value.publication_id) && (value.replayed || integer(value.revision, 1) && (context.revision === undefined || value.revision === context.revision));
  }
  if (!sameId(value.operation_id, payload.operation_id)) return false;
  if (path === "/gates") {
    const expected = scopeKey(payload, context);
    return expected !== null && typeof value.scope_key === "string" && value.scope_key.toLowerCase() === expected && (value.replayed || integer(payload.expected_version) && value.version === payload.expected_version + 1 && value.enabled === payload.enabled && typeof value.enabled === "boolean" && value.killed === payload.killed && typeof value.killed === "boolean");
  }
  const parts = path.split("/");
  if (parts.length !== 4 || !id(parts[2])) return false;
  if (parts[1] === "publications" && parts[3] === "retire") return sameId(value.publication_id, parts[2]) && value.retired === true;
  if (parts[1] === "runs" && parts[3] === "recover") return sameId(value.id, parts[2]) && (value.replayed || safeRun(value, payload));
  if (parts[1] === "actions" && parts[3] === "approve") return sameId(value.job_id, parts[2]) && (value.replayed || value.status === "pending" && integer(payload.expected_version) && value.lock_version === payload.expected_version + 1);
  if (parts[1] === "outbox" && parts[3] === "retry") return sameId(value.id, parts[2]) && (value.replayed || value.status === "retryable");
  return false;
}
/** Audit reconciliation also binds action and target, not just a matching operation UUID. */
export function runtimeAuditMatches(intent: RuntimeMutationIntent, item: HistoryItem): boolean {
  if (!object(item) || !object(item.summary)) return false;
  if (intent.path === "/publications/activate") return item.action === "activate" && id(item.target_id) && sameId(item.summary.preview_id, intent.payload.preview_id) && (intent.context.revision === undefined || item.summary.revision === intent.context.revision);
  if (!sameId(item.id, intent.payload.operation_id)) return false;
  if (intent.path === "/gates") {
    const expected = scopeKey(intent.payload, intent.context);
    return expected !== null && item.action === "gate" && typeof item.target_id === "string" && item.target_id.toLowerCase() === expected;
  }
  const parts = intent.path.split("/");
  if (parts.length !== 4 || !sameId(item.target_id, parts[2])) return false;
  return (parts[1] === "publications" && parts[3] === "retire" && item.action === "retire") || (parts[1] === "runs" && parts[3] === "recover" && item.action === "recover") || (parts[1] === "actions" && parts[3] === "approve" && item.action === "approve_action") || (parts[1] === "outbox" && parts[3] === "retry" && item.action === "retry_delivery");
}
