"use client";

import { Fragment, type ReactNode, useState } from "react";
import { useDraftNavigation } from "@/components/blocks/use-draft-navigation";
import { useRouter } from "next/navigation";
import { saveCategoryDraft } from "@/app/(console)/categories/actions";
import { DisplayOrderControls } from "@/components/blocks/display-order-controls";
import { useDisplayOrder } from "@/components/blocks/use-display-order";
import { BulkSelectCheckbox } from "@/components/blocks/bulk-unpublish-selection";
import { CategoryParentPicker } from "@/components/blocks/category-parent-picker";
import { useSectionCommand } from "@/components/runtime/use-section-command";
import { Badge } from "@/components/ui/badge";
import { DraftActions } from "@/components/ui/draft-actions";
import { Input } from "@/components/ui/input";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { OrderHandle } from "@/components/ui/order-handle";
import { categoryParentOptions, categoryPath } from "@/lib/category-tree";
import type { Category } from "@/lib/types";

type StoreCategory = Category & { store_id: string };

function CategoryRowEditor({ category, categories, blocked, orderControls, depth }: {
  category: StoreCategory;
  categories: StoreCategory[];
  blocked: boolean;
  orderControls: ReactNode;
  depth: number;
}) {
  const router = useRouter();
  const initial = { name: category.name, parent_id: category.parent_id ?? null, is_published: category.is_published };
  const [draft, setDraft] = useState(initial);
  const [open, setOpen] = useState(false);
  const command = useSectionCommand(() => saveCategoryDraft(category.id, {
    ...(draft.name.trim() !== initial.name ? { name: draft.name.trim() } : {}),
    ...(draft.parent_id !== initial.parent_id ? { parent_id: draft.parent_id } : {}),
    ...(draft.is_published !== initial.is_published ? { is_published: draft.is_published } : {}),
  }));
  const dirty = draft.name.trim() !== initial.name || draft.parent_id !== initial.parent_id ||
    draft.is_published !== initial.is_published;
  const unavailable = blocked || command.pending;

  async function save(navigating = false) {
    if (!dirty) return true;
    if (unavailable || !draft.name.trim()) return false;
    const result = await command.run(undefined);
    if (!result?.ok) return false;
    setOpen(false);
    if (!navigating) router.refresh();
    return true;
  }

  useDraftNavigation(dirty || command.pending, () => save(true));

  return <>
    <RecordClickArea as="tr" className="border-t" orderId={String(category.id)}>
      <td><div className="flex items-center gap-1 p-1" style={indent(depth)}>
        {orderControls}
        <button type="button" data-record-trigger
          className="rounded-sm px-1 font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-ring"
          aria-expanded={open} aria-controls={`category-draft-${category.id}`} disabled={unavailable}
          onClick={async () => {
            if (!open) setOpen(true);
            else if (await save()) setOpen(false);
          }}>{category.name}</button>
      </div></td>
      <td className="px-2"><CategoryStatus category={category} /></td>
    </RecordClickArea>
    {open && <tr id={`category-draft-${category.id}`}><td colSpan={2} className="border-t bg-muted/30 p-3">
      <div className="max-w-lg space-y-2">
      <label className="block text-xs">نام<Input value={draft.name} required maxLength={255}
        disabled={unavailable} onChange={event => setDraft({ ...draft, name: event.target.value })} /></label>
      <CategoryParentPicker options={categoryParentOptions(categories, category.id)}
        value={draft.parent_id} disabled={unavailable} onChange={parent_id => setDraft(previous => ({ ...previous, parent_id }))} />
      <label className="flex items-center gap-1"><input type="checkbox" checked={draft.is_published}
        disabled={unavailable} onChange={event => setDraft({ ...draft, is_published: event.target.checked })}
        className="accent-primary" /> انتشار</label>
      <DraftActions dirty={dirty} pending={unavailable} onSave={() => void save()}
        onDiscard={() => { setDraft(initial); command.clear(); setOpen(false); }} />
      {dirty && !draft.name.trim() && <p role="status" className="text-xs text-destructive">نام دسته‌بندی را وارد کنید.</p>}
      {command.result?.ok === false && <p role="alert" className="text-xs text-destructive">
        دسته‌بندی ذخیره نشد. نام، دسته‌بندی والد و دسترسی فروشگاه را بررسی کنید.
      </p>}
      </div>
    </td></tr>}
  </>;
}

function CategorySiblings({ branches, categories, parentId, depth, edit }: {
  branches: ReadonlyMap<number | null, StoreCategory[]>;
  categories: StoreCategory[];
  parentId: number | null;
  depth: number;
  edit: boolean;
}) {
  const order = useDisplayOrder(branches.get(parentId) ?? [], "categories", parentId);
  return <>
    {order.rows.map(category => {
      const children = branches.get(category.id);
      return <Fragment key={category.id}>
        {edit ? <CategoryRowEditor
          key={JSON.stringify([category.id, category.name, category.parent_id, category.is_published])}
          category={category} categories={categories} blocked={order.pending || order.needsRefresh} depth={depth}
          orderControls={<>
            <OrderHandle id={String(category.id)} label={category.name} ids={order.ids}
              move={order.move} disabled={order.pending || order.needsRefresh} />
            <BulkSelectCheckbox id={category.id} />
          </>} /> : <tr className="border-t">
            <td><div className="p-2" style={indent(depth)}>{category.name}</div></td>
            <td className="px-2"><CategoryStatus category={category} /></td>
          </tr>}
        {!!children?.length && <CategorySiblings branches={branches} categories={categories}
          parentId={category.id} depth={depth + 1} edit={edit} />}
      </Fragment>;
    })}
    {edit && <tr hidden={!order.dirty && !order.message && !order.needsRefresh}><td colSpan={2} className="p-2">
      <DisplayOrderControls order={order} />
    </td></tr>}
  </>;
}

function indent(depth: number) {
  return { paddingInlineStart: `${Math.min(depth, 6) * 1.25 + .5}rem` };
}

function CategoryStatus({ category }: { category: StoreCategory }) {
  return <Badge tone={category.is_published ? "success" : "neutral"}>
    {category.is_published ? "منتشرشده" : "پیش‌نویس"}
  </Badge>;
}

export function CategoryOrderTable({ categories, storeId, edit }: {
  categories: StoreCategory[]; storeId: string; edit: boolean;
}) {
  const current = categories.filter(row => row.store_id === storeId);
  const others = categories.filter(row => row.store_id !== storeId);
  const byId = new Map(categories.map(row => [row.id, row]));
  const currentIds = new Set(current.map(row => row.id));
  const branches = new Map<number | null, StoreCategory[]>();
  for (const row of current) {
    const parent = row.parent_id != null && currentIds.has(row.parent_id) ? row.parent_id : null;
    branches.set(parent, [...(branches.get(parent) ?? []), row]);
  }
  if (!categories.length) return <p className="py-8 text-center text-sm text-muted-foreground">هنوز دسته‌بندی‌ای تعریف نشده است.</p>;
  return <div className="overflow-x-auto rounded-md border">
    <table data-order-list className="w-full min-w-80 text-sm">
      <thead className="bg-muted"><tr><th scope="col" className="p-2 text-start">دسته‌بندی</th>
        <th scope="col" className="p-2 text-start">وضعیت</th></tr></thead>
      <tbody>
        <CategorySiblings branches={branches} categories={current} parentId={null} depth={0} edit={edit} />
        {others.map(category => <tr key={category.id} className="border-t">
          <td className="p-2">{categoryPath(category, byId)} <small className="text-muted-foreground">· فروشگاه دیگر</small></td>
          <td className="px-2"><CategoryStatus category={category} /></td>
        </tr>)}
      </tbody>
    </table>
  </div>;
}
