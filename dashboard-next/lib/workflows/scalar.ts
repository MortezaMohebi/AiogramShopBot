import type { Scalar } from "./types";
/** Parse only the shared Scalar schema; no arrays, arbitrary objects or executable expressions. */
export function parseScalar(raw: string): Scalar {
  const value: unknown = JSON.parse(raw);
  if (value === null || typeof value === "boolean" || typeof value === "string") return value;
  if (typeof value === "number" && Number.isSafeInteger(value)) return value;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const ref = value as {
      kind?: unknown;
      id?: unknown;
    };
    if (Object.keys(ref).length === 2 && typeof ref.kind === "string" && ["product", "category", "order", "customer"].includes(ref.kind) && typeof ref.id === "number" && Number.isSafeInteger(ref.id) && ref.id > 0) return value as Scalar;
  }
  throw new Error("workflow_scalar_invalid");
}
