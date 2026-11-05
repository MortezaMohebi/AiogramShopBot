/** Safe Action metadata and no-effect inspection contracts from the signed Backend. */
export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: Array<string | number | boolean>;
  anyOf?: JsonSchema[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  default?: unknown;
  [key: string]: unknown;
}
export interface ActionDescriptor {
  key: string;
  version: string;
  name: string;
  description: string;
  category: string;
  input_schema: JsonSchema;
  output_schema: JsonSchema;
  error_schema: JsonSchema;
  required_context: string[];
  allowed_actors: string[];
  required_scopes: string[];
  side_effect:
    | "none"
    | "read_only"
    | "reversible"
    | "business_mutation"
    | "external_mutation"
    | "irreversible";
  idempotency: "not_applicable" | "recommended" | "required";
  transaction: "read_only" | "atomic_local" | "outbox";
  timeout_seconds: number;
  max_retries: number;
  backoff_seconds: number;
  retry_requires_idempotency: boolean;
  retryable_codes: string[];
  confirmation: "none" | "customer_confirmation" | "operator_approval" | "both";
  platforms: Array<"telegram" | "bale">;
  service_available: boolean;
  unavailable_reason: string | null;
  dry_run: boolean;
  simulator: string;
  sensitive_inputs: string[];
  sensitive_outputs: string[];
  deprecated: boolean;
  replacement: string | null;
  availability?: { available: boolean; reasons: string[] };
  can_dry_run?: boolean;
}
export interface ActionCatalogPage {
  items: ActionDescriptor[];
  total: number;
  page: number;
  has_more: boolean;
  store_id: string;
  bot_id: string | null;
  platform: "telegram" | "bale" | null;
  runtime_available: false;
  can_inspect_data: boolean;
}
export interface ActionResult {
  status:
    | "succeeded"
    | "failed"
    | "retryable"
    | "pending_approval"
    | "pending_external"
    | "skipped"
    | "unavailable";
  output: Record<string, unknown> | null;
  error: { code: string; message: string } | null;
  dry_run: boolean;
  simulated: boolean;
  exact_preview: boolean;
  execution_receipt: string | null;
  correlation_id: string;
}
export interface InputSource {
  kind: "variable" | "constant" | "context";
  name: string;
  value:
    | string
    | number
    | boolean
    | { kind: "product" | "category" | "order" | "customer"; id: number }
    | null;
}
export interface ActionConfig {
  action_key: string;
  action_version: string;
  input_mapping: Record<string, InputSource>;
  output_mapping: Record<string, string>;
  [key: string]: unknown;
}
