import type { ProductAttribute } from "@/lib/types";

export type AttributeDraft = { rowId: string; attribute: ProductAttribute };

export function newAttributeDraft(): AttributeDraft {
  const rowId = crypto.randomUUID();
  return { rowId, attribute: {
    key: `attr-${rowId}`, label: "", values: [],
    unit: null, visible: true, variation: false,
  } };
}

export function duplicateAttributeDraft(source: ProductAttribute): AttributeDraft {
  const draft = newAttributeDraft();
  // Only the product association is copied; shared definitions and terms keep their IDs.
  return { ...draft, attribute: {
    ...draft.attribute,
    label: source.label, definition_id: source.definition_id, unit: source.unit, visible: source.visible,
    variation: source.variation, aliases: [...(source.aliases ?? [])],
    values: source.values.map(({ label, value_id }) => ({ label, value_id })),
  } };
}

export function moveAttributeDraft(rows: AttributeDraft[], from: string, to: string): AttributeDraft[] {
  const source = rows.findIndex(({ rowId }) => rowId === from);
  const target = rows.findIndex(({ rowId }) => rowId === to);
  if (source < 0 || target < 0 || source === target) return rows;
  const next = [...rows];
  const [row] = next.splice(source, 1);
  next.splice(target, 0, row);
  return next;
}
