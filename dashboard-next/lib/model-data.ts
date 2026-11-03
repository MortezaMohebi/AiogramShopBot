/** Reusable field/query contracts for all registered admin data models. */

export type ModelName = "products" | "customers" | "orders";
export type FieldOperator = "eq" | "ne" | "contains" | "starts" | "gte" | "lte" | "in";
export type TimeGranularity = "day" | "week" | "month" | "quarter" | "year";

export interface ModelField {
  key: string;
  title: string;
  kind: "string" | "enum" | "uuid" | "integer" | "money" | "datetime" | "boolean";
  sortable: boolean;
  searchable: boolean;
  groupable: boolean;
  importable: boolean;
  exportable: boolean;
  required: boolean;
}

export interface ModelMetadata {
  model: ModelName;
  label: string;
  can_import: boolean;
  fields: ModelField[];
  time_granularities: TimeGranularity[];
}

export interface ModelFilter {
  field: string;
  op: FieldOperator;
  value: string | number | boolean | Array<string | number | boolean> | null;
}

export interface ModelSearchRequest {
  filters: ModelFilter[];
  page: number;
  page_size: number;
  sort_by: string;
  descending: boolean;
}

export interface ModelSearchResult {
  model: ModelName;
  page: number;
  page_size: number;
  total: number;
  items: Record<string, string | boolean | number | null>[];
}

export interface ModelGroupResult {
  model: ModelName;
  field: string;
  granularity: TimeGranularity | null;
  timezone: string | null;
  items: { bucket: string | number | boolean | null; count: number }[];
}

export interface ModelImportPreview {
  model: ModelName;
  rows: number;
  creates: number;
  updates: number;
  sha256: string;
  preview_id?: string;
  preview_expires_at?: string;
  preview: { row: number; action: "create" | "update" }[];
  committed: boolean;
}
