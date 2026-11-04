/** Portable server-owned contracts. Canvas objects and preview state never enter Definition. */
export type Platform = "telegram" | "bale";
export type Scalar =
  | string
  | number
  | boolean
  | { kind: "product" | "order" | "customer"; id: number }
  | null;
export type VariableType =
  | "string"
  | "integer"
  | "decimal"
  | "boolean"
  | "date"
  | "datetime"
  | "enum"
  | "product_ref"
  | "order_ref"
  | "customer_ref";
export interface Variable {
  name: string;
  type: VariableType;
  scope: "workflow" | "input";
  label: string;
  choices: string[];
  default: Scalar;
}
export type Condition =
  | {
      kind: "rule";
      variable: string;
      operator: "eq" | "neq" | "gt" | "lt" | "contains" | "exists" | "is_empty";
      value: Scalar;
    }
  | { kind: "all" | "any"; terms: Condition[] };
export interface WorkflowButton {
  key: string;
  label: string;
  type:
    | "callback"
    | "url"
    | "action"
    | "request_contact"
    | "back"
    | "cancel"
    | "main_menu";
  row: number;
  target: string;
  action: string;
  url: string;
  visible_when: Condition | null;
  platforms: Platform[];
}
export interface Choice {
  key: string;
  label: string;
  value: Scalar;
}
export type Config = Record<string, unknown>;
export interface DomainNode {
  id: string;
  type: string;
  label: string;
  config: Config;
  platform_overrides: Partial<Record<Platform, Config>>;
  max_visits: number | null;
}
export interface DomainEdge {
  id: string;
  source: string;
  target: string;
  port: string;
}
export interface EntryPoint {
  kind: "start" | "command" | "menu" | "internal";
  key: string;
  node_id: string;
  command: string;
}
export interface Definition {
  schema_version: 1;
  target_platforms: Platform[];
  assignment: { mode: "selected" | "all_eligible"; bot_ids: string[] };
  entry_points: EntryPoint[];
  nodes: DomainNode[];
  edges: DomainEdge[];
  variables: Variable[];
  error_policy: {
    max_steps: number;
    on_error: "stop" | "cancel";
    message: string;
  };
  timeout_policy: { seconds: number; outcome: "cancel" | "end" };
}
export interface EditorLayout {
  positions: Record<string, { x: number; y: number }>;
  viewport: { x: number; y: number; zoom: number };
}
export interface DraftDocument {
  name: string;
  description: string;
  definition: Definition;
  layout: EditorLayout;
}
export interface Issue {
  code: string;
  message: string;
  severity: "error" | "warning";
  node_id: string | null;
  field: string | null;
  platform: Platform | null;
  blocks_activation: boolean;
}
export interface ValidationReport {
  valid: boolean;
  can_simulate: boolean;
  activation_available: false;
  issues: Issue[];
}
export interface WorkflowRecord extends DraftDocument {
  id: string;
  store_id: string;
  key: string;
  status: "draft" | "archived" | "deleted";
  revision: number;
  head_revision: number;
  can_write: boolean;
  validation: ValidationReport;
  runtime_available: false;
  created_at?: string;
  updated_at?: string;
}
export interface FieldSpec {
  key: string;
  label: string;
  kind: string;
  required: boolean;
  options: string[];
  help: string;
  show_if: Record<string, unknown>;
  schema: Record<string, unknown>;
  overridable?: boolean;
}
export interface NodeSpec {
  type: string;
  label: string;
  group: string;
  ports: string[];
  defaults: Config;
  fields: FieldSpec[];
  action_contract: {
    key: string;
    service: string | null;
    available: boolean;
    execution_available: false;
    simulation_only: boolean;
  };
}
export interface Catalog {
  nodes: NodeSpec[];
  platforms: Record<Platform, Record<string, unknown>>;
  can_write: boolean;
  store_id: string;
  runtime_available: false;
  limits: {
    nodes: number;
    edges: number;
    variables: number;
    request_bytes: number;
  };
}
export interface BotChoice {
  id: string;
  name: string;
  platform: Platform;
  status: string;
}
export interface MediaChoice {
  id: number;
  name: string | null;
  kind: string;
  size_bytes: number | null;
  product_name: string;
}
export interface ChoicePage<T> {
  items: T[];
  page: number;
  has_more: boolean;
}
export interface ListItem {
  id: string;
  store_id: string;
  key: string;
  name: string;
  description: string;
  status: WorkflowRecord["status"];
  revision: number;
  updated_at: string;
}
export interface WorkflowList extends ChoicePage<ListItem> {
  total: number;
}
export interface Revision {
  revision: number;
  operation_id: string;
  action: string;
  created_by: number;
  created_at: string;
  sha256: string;
}
export interface RevisionPage extends ChoicePage<Revision> {
  head_revision: number;
}
export interface Diff {
  left_revision: number;
  right_revision: number;
  nodes: { added: string[]; removed: string[]; changed: string[] };
  edges: Diff["nodes"];
  variables: Diff["nodes"];
  metadata_changed: string[];
  layout_changed: boolean;
  definition_changed: boolean;
}
export interface SimulationEvent {
  kind: "input" | "button" | "back" | "cancel" | "tick";
  value?: Scalar;
  key?: string;
  file?: { name: string; mime_type: string; size_bytes: number };
  seconds?: number;
}
export interface PreviewMessage {
  node_id: string;
  kind: string;
  text: string;
  [key: string]: unknown;
}
export interface SimulationResult {
  status: string;
  code: string;
  active_node_id: string | null;
  messages: PreviewMessage[];
  buttons: {
    key: string;
    label: string;
    row: number;
    type: string;
    url?: string;
  }[];
  input: { type?: string; kind?: string; [key: string]: unknown } | null;
  values: Record<string, Scalar>;
  visited: string[];
  stub_actions: string[];
  elapsed_seconds: number;
  can_go_back: boolean;
  simulation_only: true;
  validation: ValidationReport;
  revision: number;
  head_revision: number;
}
