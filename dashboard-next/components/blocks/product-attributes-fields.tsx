import { useId, useState } from "react";
import { flushSync } from "react-dom";
import Link from "next/link";
import { ChevronDown, ChevronLeft, Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OrderHandle, orderOperations } from "@/components/ui/order-handle";
import { RelationTag } from "@/components/ui/relation-tag";
import { CatalogSpecPicker } from "@/components/blocks/catalog-spec-picker";
import { CatalogSpecDialog } from "@/components/blocks/catalog-spec-dialog";
import {
  duplicateAttributeDraft, moveAttributeDraft, newAttributeDraft, type AttributeDraft,
} from "@/lib/product-attribute-drafts";
import type { ProductAttribute } from "@/lib/types";
import type { CatalogKind, CatalogSpec } from "@/lib/catalog-specs";

const operations = orderOperations;
export function ProductAttributesFields({ rows, saved, storeId, error, onChange }: {
  rows: AttributeDraft[];
  saved: ProductAttribute[];
  storeId: string;
  error?: string;
  onChange: (rows: AttributeDraft[]) => void;
}) {
  const fieldId = useId();
  const [expanded, setExpanded] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const [editor, setEditor] = useState<{
    kind: CatalogKind; rowId: string; item?: CatalogSpec; parent?: CatalogSpec; initialLabel?: string;
  } | null>(null);

  function attach(rowId: string, kind: CatalogKind, item: CatalogSpec, editing = false) {
    onChange(rows.map((row) => {
      const attribute = row.attribute;
      if (kind === "attributes" && (editing ? attribute.definition_id === item.id : row.rowId === rowId)) {
        return { ...row, attribute: {
          ...attribute, definition_id: item.id, label: item.label, unit: item.unit ?? null,
          aliases: item.aliases, external_ids: undefined,
          values: attribute.definition_id === item.id ? attribute.values : [],
        } };
      }
      if (kind === "values" && attribute.definition_id === item.definition_id) {
        if (editing) {
          return { ...row, attribute: { ...attribute, values: attribute.values.map((value) =>
            value.value_id === item.id ? { ...value, label: item.label } : value) } };
        }
        if (row.rowId === rowId && !attribute.values.some((value) => value.value_id === item.id)) {
          return { ...row, attribute: { ...attribute, values: [...attribute.values, { value_id: item.id, label: item.label }] } };
        }
      }
      return row;
    }));
  }

  function insert(draft: AttributeDraft, at = rows.length) {
    if (rows.length >= 12) return;
    onChange([...rows.slice(0, at), draft, ...rows.slice(at)]);
    requestAnimationFrame(() => document.getElementById(`${fieldId}-${draft.rowId}`)?.focus());
  }

  function reorder(from: string, to: string) {
    const next = moveAttributeDraft(rows, from, to);
    if (next === rows) return;
    onChange(next);
    const position = next.findIndex(({ rowId }) => rowId === from);
    setAnnouncement(`اولویت ${next[position].attribute.label || "ویژگی"} به ${position + 1} تغییر کرد.`);
  }

  return (
    <section aria-labelledby="product-attributes-title" className="space-y-3 border-t pt-5" dir="rtl">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="product-attributes-title" tabIndex={-1} className="text-sm font-semibold">ویژگی‌های محصول</h3>
        <div className="flex flex-wrap gap-3 text-sm text-primary">
          <Link className="hover:underline" href="/product-attributes" target="_blank" rel="noopener">مدیریت ویژگی‌ها<span className="sr-only"> (برگهٔ جدید)</span></Link>
          <Link className="hover:underline" href="/product-attribute-values" target="_blank" rel="noopener">مدیریت مقدارها<span className="sr-only"> (برگهٔ جدید)</span></Link>
        </div>
      </div>
      <p id={`${fieldId}-priority`} className="text-sm text-muted-foreground">
        ویژگی و مقدارها را از فهرست انتخاب کنید. برای تغییر ترتیب از دستگیره یا کلیدهای بالا و پایین استفاده کنید.
      </p>
      <p role="status" className="sr-only">{announcement}</p>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <div className="overflow-x-auto rounded-md border">
        <table data-order-list aria-labelledby="product-attributes-title" className="w-full min-w-[30rem] border-separate border-spacing-0 text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr className="text-start [&>th]:border-b [&>th]:py-2">
              <th scope="col" className="min-w-44 ps-20 pe-2 text-start font-medium">ویژگی</th>
              <th scope="col" className="w-24 px-2 text-start font-medium">واحد</th>
              <th scope="col" className="min-w-36 px-2 text-start font-medium">مقادیر</th>
              <th scope="col" className="w-14 px-2 text-center font-medium">نمایش</th>
              <th scope="col" className={`${operations} w-20 bg-muted text-center font-medium`}>عملیات</th>
            </tr>
          </thead>
          {rows.map(({ rowId, attribute }, index) => {
            const open = expanded.includes(rowId);
            const name = attribute.label || `ویژگی ${index + 1}`;
            const definition = attribute.definition_id ? {
              id: attribute.definition_id, label: attribute.label, unit: attribute.unit, aliases: attribute.aliases,
            } : undefined;
            const update = (patch: Partial<ProductAttribute>) => onChange(rows.map((row) =>
              row.rowId === rowId ? { ...row, attribute: { ...row.attribute, ...patch } } : row,
            ));
            return (
              <tbody key={rowId} data-order-row={rowId} onInvalidCapture={(event) => {
                if (!open) flushSync(() => setExpanded((items) => [...items, rowId]));
                const details = (event.target as HTMLElement).closest("details");
                if (details) details.open = true;
              }}>
                <tr className="[&>td]:border-b">
                  <td className="py-1.5 pe-2">
                    <div className="flex items-center gap-0.5 ps-1">
                      <OrderHandle id={rowId} label={name} ids={rows.map((row) => row.rowId)} move={reorder} />
                      <Button type="button" variant="ghost" size="icon" className="size-8"
                        aria-expanded={open} aria-label={`${open ? "بستن" : "باز کردن"} تنظیمات ${name}`}
                        onClick={() => setExpanded((items) => open ? items.filter((id) => id !== rowId) : [...items, rowId])}>
                        {open ? <ChevronDown aria-hidden="true" /> : <ChevronLeft aria-hidden="true" />}
                      </Button>
                      <CatalogSpecPicker id={`${fieldId}-${rowId}`} storeId={storeId} kind="attributes"
                        label={attribute.label || "انتخاب ویژگی"} onSelect={(item) => attach(rowId, "attributes", item)}
                        onCreate={(initialLabel) => setEditor({ kind: "attributes", rowId, initialLabel })} />
                      {definition && <Button type="button" variant="ghost" size="icon" className="size-8"
                        aria-label={`ویرایش تعریف ${name}`} title="ویرایش تعریف ویژگی"
                        onClick={() => setEditor({ kind: "attributes", rowId, item: definition })}>
                        <Pencil aria-hidden="true" />
                      </Button>}
                    </div>
                  </td>
                  <td className="px-2 py-1.5">
                    <bdi className="text-muted-foreground">{attribute.unit || "—"}</bdi>
                  </td>
                  <td className="px-2 py-1.5">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {attribute.values.map((value, valueIndex) => (
                        <RelationTag key={value.value_id ?? valueIndex} label={value.label}
                          removeLabel={`برداشتن مقدار ${value.label} از ${name}`}
                          onRemove={() => update({ values: attribute.values.filter((_, position) => position !== valueIndex) })}
                          onEdit={value.value_id && definition ? () => setEditor({ kind: "values", rowId, parent: definition,
                            item: { id: value.value_id!, label: value.label, definition_id: definition.id } }) : undefined} />
                      ))}
                      {definition && attribute.values.length < 8 && <CatalogSpecPicker storeId={storeId}
                        kind="values" definitionId={definition.id} label="افزودن مقدار"
                        exclude={attribute.values.flatMap((value) => value.value_id ? [value.value_id] : [])}
                        onSelect={(item) => attach(rowId, "values", item)}
                        onCreate={(initialLabel) => setEditor({ kind: "values", rowId, parent: definition, initialLabel })} />}
                    </div>
                  </td>
                  <td className="px-2 text-center">
                    <input type="checkbox" aria-label={`نمایش ${name} در کارت محصول`}
                      checked={attribute.visible} className="size-4 accent-primary"
                      onChange={(event) => update({ visible: event.target.checked })} />
                  </td>
                  <td className={operations}>
                    <div className="flex justify-center gap-0.5">
                      <Button type="button" variant="ghost" size="icon" className="size-8"
                        title="تکثیر ردیف" aria-label={`تکثیر ${name}`} disabled={rows.length >= 12}
                        onClick={() => insert(duplicateAttributeDraft(attribute), index + 1)}><Copy aria-hidden="true" /></Button>
                      <Button type="button" variant="ghost" size="icon" className="size-8 text-destructive"
                        title="حذف ردیف" aria-label={`حذف ${name}`} onClick={() => {
                          setExpanded((items) => items.filter((id) => id !== rowId));
                          onChange(rows.filter((row) => row.rowId !== rowId));
                        }}><Trash2 aria-hidden="true" /></Button>
                    </div>
                  </td>
                </tr>
                <tr hidden={!open} className="bg-muted/30">
                  <td colSpan={5} className="space-y-2 border-b py-2 pe-3 ps-10">
                    <details className="space-y-3 border-s-2 border-border ps-3 text-sm">
                      <summary className="cursor-pointer text-muted-foreground">تنظیمات ویژگی</summary>
                      <label className="block space-y-1">کد ویژگی
                        <Input dir="ltr" required maxLength={48} pattern={"[a-z][a-z0-9_\\-]{0,47}"}
                          value={attribute.key} readOnly={saved.some((item) => item.key === rowId)}
                          onChange={(event) => update({ key: event.target.value })} />
                      </label>
                      <label className="flex items-center gap-2">
                        <input type="checkbox" checked={attribute.variation} className="accent-primary"
                          onChange={(event) => update({ variation: event.target.checked })} />
                        قابل استفاده برای گونه‌ها در فروشگاه بیرونی
                      </label>
                    </details>
                  </td>
                </tr>
              </tbody>
            );
          })}
          <tfoot>
            <tr><td colSpan={5} className="px-2 py-1">
              <Button type="button" size="sm" variant="ghost" className="text-primary"
                disabled={rows.length >= 12} onClick={() => insert(newAttributeDraft())}>
                <Plus aria-hidden="true" /> افزودن ویژگی
              </Button>
            </td></tr>
          </tfoot>
        </table>
      </div>
      {editor && <CatalogSpecDialog storeId={storeId} kind={editor.kind} item={editor.item}
        initialLabel={editor.initialLabel} parent={editor.parent} onClose={() => setEditor(null)}
        onSaved={(item) => {
          attach(editor.rowId, editor.kind, item, Boolean(editor.item));
          setEditor(null);
        }} />}
    </section>
  );
}
