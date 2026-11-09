"use client";

import { useCallback } from "react";
import { RelationPicker, type RelationOption } from "@/components/ui/relation-picker";

const normalize = (text: string) => text.normalize("NFKC").trim().toLowerCase()
  .replace(/[يى]/g, "ی").replace(/ك/g, "ک")
  .replace(/[۰-۹٠-٩]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩".indexOf(digit) % 10));

export function LocalRelationPicker<T extends RelationOption>({ items, exclude, ...props }: {
  items: readonly T[];
  label: string;
  exclude?: T["id"][];
  onSelect: (item: T) => void;
  onCreate?: (query: string) => void;
  createLabel?: string;
  disabled?: boolean;
  maxLength?: number;
}) {
  const load = useCallback(async (query: string, page: number) => {
    const search = normalize(query);
    const matching = items.filter((item) => !exclude?.includes(item.id)
      && normalize(`${item.label} ${item.detail ?? ""}`).includes(search));
    return { items: matching.slice((page - 1) * 25, page * 25), has_more: matching.length > page * 25 };
  }, [items, exclude]);
  return <RelationPicker {...props} load={load} sourceKey="local" />;
}
