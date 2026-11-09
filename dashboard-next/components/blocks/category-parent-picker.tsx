"use client";

import { useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LocalRelationPicker } from "@/components/ui/local-relation-picker";

export function CategoryParentPicker({ options, initial = null, value, onChange, disabled }: {
  options: { id: number; label: string }[];
  initial?: number | null;
  value?: number | null;
  onChange?: (value: number | null) => void;
  disabled?: boolean;
}) {
  const [local, setLocal] = useState(initial);
  const selected = onChange ? value : local;
  const choose = onChange ?? setLocal;
  const label = options.find(item => item.id === selected)?.label;
  return <div className="min-w-0 space-y-1">
    <span className="text-xs font-medium">دسته‌بندی والد</span>
    <input type="hidden" name="parent_id" value={selected ?? ""} />
    <div className="flex min-w-0 items-center gap-1">
      <LocalRelationPicker items={options} label={label ?? "بدون والد"}
        disabled={disabled} onSelect={item => choose(item.id)} />
      {selected != null && <Button type="button" size="icon" variant="ghost" aria-label="برداشتن والد"
        disabled={disabled} onClick={() => choose(null)}><X aria-hidden="true" /></Button>}
    </div>
  </div>;
}
