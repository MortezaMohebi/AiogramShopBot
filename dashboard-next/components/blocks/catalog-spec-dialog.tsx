"use client";

import { useRef, useState } from "react";
import { CatalogSpecPicker } from "@/components/blocks/catalog-spec-picker";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { DraftActions } from "@/components/ui/draft-actions";
import { Input } from "@/components/ui/input";
import { catalogSpecError, saveCatalogSpec, type CatalogKind, type CatalogSpec } from "@/lib/catalog-specs";

/** Edit a shared record without navigating away or submitting a product form. */
export function CatalogSpecDialog({ storeId, kind, item, initialLabel, parent, onClose, onSaved }: {
  storeId: string;
  kind: CatalogKind;
  item?: CatalogSpec;
  initialLabel?: string;
  parent?: CatalogSpec;
  onClose: () => void;
  onSaved: (record: CatalogSpec) => void;
}) {
  const [label, setLabel] = useState(item?.label ?? initialLabel ?? "");
  const [unit, setUnit] = useState(item?.unit ?? "");
  const [aliases, setAliases] = useState(item?.aliases?.join("، ") ?? "");
  const [selectedParent, setParent] = useState(parent ?? (item?.definition_id
    ? { id: item.definition_id, label: item.attribute_label ?? "" } : undefined));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const locked = useRef(false);
  const title = `${item ? "ویرایش" : "تعریف"} ${kind === "attributes" ? "ویژگی" : "مقدار"}`;
  const ready = Boolean(label.trim() && (kind === "attributes" || selectedParent));
  const dirty = Boolean(item && (label !== item.label || unit !== (item.unit ?? "") ||
    aliases !== (item.aliases?.join("، ") ?? "")));

  async function save() {
    if (locked.current || (item && !dirty)) return;
    if (!ready) {
      setError("عنوان و ویژگی را بررسی کنید.");
      return;
    }
    const terms = aliases.split(/[،,]/).map((part) => part.trim()).filter(Boolean);
    if (kind === "attributes" && (terms.length > 6 || terms.some((part) => part.length > 80))) {
      setError("حداکثر ۶ عبارت جایگزین و برای هرکدام حداکثر ۸۰ نویسه وارد کنید.");
      return;
    }
    locked.current = true;
    setPending(true);
    setError("");
    try {
      const record = await saveCatalogSpec(storeId, kind, kind === "attributes"
        ? { label: label.trim(), unit: unit.trim() || null, aliases: terms }
        : { label: label.trim(), definition_id: selectedParent?.id }, item?.id);
      onSaved(record);
    } catch (failure) {
      setError(catalogSpecError(failure));
    } finally {
      setPending(false);
      locked.current = false;
    }
  }

  return <Dialog open onClose={() => { if (!locked.current) onClose(); }} label={title}>
    <div className="space-y-4 p-5" dir="rtl" aria-busy={pending}>
      <h2 className="text-lg font-semibold">{title}</h2>
      {item && <p className="text-sm text-muted-foreground">تغییر این تعریف در همهٔ محصولاتی که از آن استفاده می‌کنند دیده می‌شود.</p>}
      <label className="block space-y-1 text-sm">عنوان
        <Input autoFocus value={label} maxLength={80} onChange={(event) => setLabel(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void save(); } }} />
      </label>
      {kind === "attributes" ? <>
        <label className="block space-y-1 text-sm">واحد (اختیاری)
          <Input dir="auto" value={unit} maxLength={24} onChange={(event) => setUnit(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }} />
        </label>
        <label className="block space-y-1 text-sm">عبارت‌های جایگزین برای سؤال مشتری
          <Input value={aliases} maxLength={490} placeholder="با ویرگول جدا کنید" onChange={(event) => setAliases(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }} />
        </label>
      </> : item || parent ? <p className="text-sm">ویژگی: <bdi>{selectedParent?.label}</bdi></p>
        : <div><p className="text-sm">ویژگی</p><CatalogSpecPicker contained storeId={storeId} kind="attributes"
          label={selectedParent?.label ?? "انتخاب ویژگی"} onSelect={setParent} /></div>}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {item ? <DraftActions dirty={dirty} pending={pending} onSave={() => void save()} onDiscard={onClose} /> :
      <div className="flex gap-2">
        <Button type="button" disabled={!ready || pending} onClick={() => void save()}>{pending ? "در حال ذخیره…" : "ذخیره"}</Button>
        <Button type="button" variant="outline" disabled={pending} onClick={onClose}>انصراف</Button>
      </div>}
    </div>
  </Dialog>;
}
