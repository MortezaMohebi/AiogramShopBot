"use client";

import { useCallback } from "react";
import { RelationPicker } from "@/components/ui/relation-picker";
import { catalogSpecError, readCatalogSpecs, type CatalogKind, type CatalogSpec } from "@/lib/catalog-specs";

export function CatalogSpecPicker({ storeId, kind, definitionId, ...props }: {
  storeId: string;
  kind: CatalogKind;
  label: string;
  definitionId?: number;
  exclude?: number[];
  onSelect: (item: CatalogSpec) => void;
  onCreate?: (query: string) => void;
  contained?: boolean;
  id?: string;
}) {
  const load = useCallback(async (query: string, page: number, signal: AbortSignal) => {
    const result = await readCatalogSpecs(storeId, kind, query, page, definitionId, signal);
    return { ...result, items: result.items.map((item) => ({ ...item, detail: item.unit ?? undefined })) };
  }, [storeId, kind, definitionId]);
  return <RelationPicker {...props} load={load} errorMessage={catalogSpecError}
    sourceKey={JSON.stringify([storeId, kind, definitionId])}
    createLabel={kind === "attributes" ? "تعریف ویژگی" : "تعریف مقدار"} />;
}
