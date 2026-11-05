/** Server-owned, Store-scoped metadata. Customer values and proof tokens are never part of these contracts. */
import type { Platform, Definition, ChoicePage } from "../workflows/types";
export type Page<T> = ChoicePage<T>;
export interface RuntimeGate {
  scope_key: string;
  bot_id: string | null;
  enabled: boolean;
  killed: boolean;
  version: number;
}
export interface RuntimeOverview {
  global_enabled: boolean;
  global_killed: boolean;
  can_publish: boolean;
  can_manage: boolean;
  runs: Record<string, number>;
  deliveries: Record<string, number>;
  supported_nodes: string[];
  gates: RuntimeGate[];
  /** Optional during API rollout; absence is unavailable, never a measured zero. */
  metrics?: RuntimeMetrics;
  active_groups?: RuntimeActiveGroup[];
  active_groups_has_more?: boolean;
  metrics_scope?: {
    store_id: string;
    window: "all_retained_history";
    duration: string;
    delivery_failures: string;
    active: string;
  };
}
export interface RuntimeActiveGroup {
  workflow_id: string;
  publication_id: string;
  revision: number;
  active_runs: number;
}
export interface RuntimeMetrics {
  runs_started: number;
  runs_completed: number;
  runs_cancelled: number;
  runs_failed: number;
  completed_duration_seconds_avg: number | null;
  node_transitions: number;
  input_validation_errors: number;
  action_failures: number;
  timeouts: number;
  duplicate_events: number;
  outbox_retries: number;
  outbox_deadletters: number;
  delivery_failures_by_platform: Partial<Record<Platform, number>>;
}
export interface Publication {
  id: string;
  workflow_id: string;
  revision: number;
  digest: string;
  active_bindings: number;
  retired: boolean;
  created_at: string;
}
export type EntryKind = "command" | "menu" | "start" | "internal" | "legacy_bridge" | "admin_test";
export interface BindingSpec {
  bot_id: string;
  kind: EntryKind;
  key: string;
  node_id: string;
  priority: number;
  enabled: boolean;
  eligibility: "all" | "existing_customer";
  fallback: "legacy" | "ignore";
  version_policy: "active_publication";
}
export interface Binding extends Omit<BindingSpec, "version_policy"> {
  id: string;
  workflow_id: string;
  publication_id: string;
  version: number;
}
/** Existing immutable activation pointer, including its owning Bot and entry node. */
export interface PublicationBindingPointer {
  id: string;
  bot_id: string;
  node_id: string;
  version: number;
  publication_id: string;
  kind: EntryKind;
  key: string;
  enabled: boolean;
}
export interface PublicationPreview {
  preview_id: string;
  expires_at: string;
  ready: boolean;
  issues: {
    code: string;
    severity?: string;
    node_id?: string | null;
    message?: string;
  }[];
  dependencies: {
    node_id: string;
    key: string;
    version: string;
    confirmation: string;
    side_effect: string;
  }[];
  mutating_nodes: string[];
  platforms: Platform[];
  diff: {
    previous_revision: number | null;
    next_revision: number;
    definition_changed: boolean;
    previous_bindings: PublicationBindingPointer[];
    unchanged_bindings: PublicationBindingPointer[];
    retains_unselected_bindings: true;
    next_bindings: BindingSpec[];
  };
}
export interface Run {
  id: string;
  store_id: string;
  bot_id: string;
  workflow_id: string;
  publication_id: string;
  node_id: string;
  platform: Platform;
  status: string;
  lock_version: number;
  created_at: string;
  updated_at: string;
  expires_at: string;
  correlation_id: string;
  error_code: string | null;
}
export interface OutboxItem {
  id: string;
  run_id: string;
  node_id: string;
  sequence: number;
  status: string;
  attempts: number;
  message_ids: string[];
  error_code: string | null;
  kind: string;
  can_retry?: boolean;
  expected_attempts?: number;
}
export interface ActionJob {
  id: string;
  key: string;
  version: string;
  node_id: string;
  status: string;
  receipt_id: string | null;
  attempts: number;
  error_code: string | null;
  can_approve?: boolean;
  expected_version?: number;
}
export interface RunDetail extends Run {
  revision: number;
  variables: {
    name: string;
    type: string;
    is_set: boolean;
    value: "[private]";
  }[];
  events: {
    id: string;
    kind: string;
    node_id: string;
    status: string;
    summary: Record<string, unknown>;
    error_code: string | null;
    created_at: string;
  }[];
  actions: ActionJob[];
  outbox: OutboxItem[];
}
export interface HistoryItem {
  id: string;
  action: string;
  target_id: string;
  summary: {
    revision?: number;
    preview_id?: string;
    request_digest?: string;
  };
  created_at: string;
}
export interface PublishSource {
  id: string;
  name: string;
  revision: number;
  definition: Definition;
}
export type RecoveryOperation = "resume" | "retry_failed" | "cancel" | "mark_failed";

/** Minimal browser recovery projection; private variables and event history stay outside client props. */
export type RecoveryTarget = Pick<RunDetail, "id" | "status" | "lock_version" | "expires_at"> & {
  actions: Pick<ActionJob, "status">[];
  outbox: Pick<OutboxItem, "status" | "error_code">[];
};
