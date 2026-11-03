"use client";

import { useRef, useState } from "react";
import { Check, ChevronDown, Pencil, Plus, Search } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import type { Category } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/**
 * Searchable and editable many2one-style category selection.
 *
 * The hidden native form value is the database ID. Creating and editing
 * categories happens inline through the permission-checked backend; new
 * categories are unpublished until explicitly approved.
 */
export function CategoryPicker({
  initial, selectedId,
}: { initial: Category[]; selectedId: number | null }) {
  const [categories, setCategories] = useState(initial);
  const [selected, setSelected] = useState<number | null>(selectedId);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [working, setWorking] = useState(false);
  const [editing, setEditing] = useState<Category | null>(null);
  const [draftName, setDraftName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const modal = useRef<HTMLDialogElement>(null);

  const current = categories.find((item) => item.id === selected);
  const filtered = categories.filter((item) =>
    item.name.toLocaleLowerCase("fa").includes(query.toLocaleLowerCase("fa")),
  );

  function showModal(item: Category | null) {
    setEditing(item);
    setDraftName(item?.name ?? query.trim());
    setError(null);
    setExpanded(false);
    modal.current?.showModal();
  }

  async function update() {
    const name = draftName.trim();
    if (!name || name.length > 255) { setError("عنوان دسته‌بندی را وارد کنید."); return; }
    if (working) return;
    setWorking(true);
    setError(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/category-picker", {
        method: editing ? "PATCH" : "POST", credentials: "same-origin",
        cache: "no-store", redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ name, ...(editing ? { id: editing.id } : {}) }),
        signal: AbortSignal.timeout(25_000),
      });
      const result = await response.json() as { ok?: boolean; id?: number; code?: string };
      if (!response.ok || result.ok !== true || !Number.isSafeInteger(result.id)) {
        setError(result.code === "category_exists" ? "این نام دسته‌بندی قبلاً ثبت شده است." :
          result.code === "permission_denied" ? "اجازهٔ ویرایش دسته‌بندی را ندارید." :
            "ذخیرهٔ دسته‌بندی انجام نشد.");
        return;
      }
      const listing = await fetch("/api/admin/category-picker", {
        method: "GET", credentials: "same-origin", cache: "no-store",
        redirect: "error", signal: AbortSignal.timeout(15_000),
      });
      const outcome = await listing.json() as { ok?: boolean; items?: Category[] };
      if (!listing.ok || outcome.ok !== true || !Array.isArray(outcome.items)) {
        setError("ذخیره شد، اما فهرست به‌روز نشد؛ صفحه را تازه‌سازی کنید.");
        return;
      }
      setCategories(outcome.items);
      setSelected(result.id ?? null);
      setQuery("");
      modal.current?.close();
    } catch {
      setError("ارتباط با سرویس دسته‌بندی برقرار نشد.");
    } finally {
      setWorking(false);
    }
  }

  return <div className="space-y-2 text-sm font-medium">
    <label htmlFor="category-search">دسته‌بندی</label>
    <input name="category_id" type="hidden" value={selected ?? ""} />
    <div className="relative">
      <button type="button" aria-expanded={expanded} aria-controls="category-options"
        onClick={() => setExpanded((value) => !value)}
        className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 text-right">
        <span className="truncate">{current?.name ?? "انتخاب یا تعریف دسته‌بندی"}</span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      </button>
      {expanded ? <div id="category-options" className="absolute z-30 mt-1 w-full rounded-lg border bg-popover p-2 shadow-xl">
        <div className="relative">
          <Search aria-hidden="true" className="absolute start-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input id="category-search" autoFocus value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="جست‌وجو در دسته‌بندی‌ها…" className="ps-9" />
        </div>
        <div className="mt-2 max-h-52 overflow-y-auto">
          <button type="button" onClick={() => { setSelected(null); setExpanded(false); }}
            className="flex w-full items-center justify-between rounded p-2 text-right hover:bg-muted">
            بدون دسته‌بندی {selected === null ? <Check className="size-4" /> : null}
          </button>
          {filtered.map((category) => <div key={category.id} className="flex items-center gap-1">
            <button type="button" onClick={() => { setSelected(category.id); setExpanded(false); setQuery(""); }}
              className="flex min-w-0 flex-1 items-center justify-between rounded p-2 text-right hover:bg-muted">
              <span className="truncate">{category.name}</span>
              {selected === category.id ? <Check className="size-4" /> : null}
            </button>
            <button type="button" aria-label={`ویرایش دسته‌بندی ${category.name}`}
              onClick={() => showModal(category)}
              className="rounded p-2 text-muted-foreground hover:bg-muted"><Pencil className="size-4" /></button>
          </div>)}
        </div>
        <Button type="button" variant="outline" className="mt-2 w-full" onClick={() => showModal(null)}>
          <Plus className="size-4" /> ایجاد دسته‌بندی جدید
        </Button>
      </div> : null}
    </div>
    {current ? <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span>دستهٔ انتخابی: {current.name}</span>
      <button type="button" className="underline" onClick={() => showModal(current)}>ویرایش</button>
    </div> : null}
    <dialog ref={modal} onClose={() => setError(null)}
      className="m-auto w-[min(94vw,30rem)] rounded-xl border border-border bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-black/60">
      <div className="space-y-4 p-6" dir="rtl">
        <p className="text-xs text-muted-foreground">محصول / دسته‌بندی / {editing ? "ویرایش" : "ایجاد"}</p>
        <h2 className="text-lg font-bold">{editing ? "ویرایش دسته‌بندی" : "دسته‌بندی جدید"}</h2>
        <label className="block space-y-2 text-sm">نام دسته‌بندی
          <Input value={draftName} onChange={(event) => setDraftName(event.target.value)}
            maxLength={255} autoFocus onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void update(); } }} />
        </label>
        <p className="text-xs leading-6 text-muted-foreground">دسته‌بندی جدید برای مشتریان منتشر نمی‌شود تا وضعیت انتشار آن تأیید شود.</p>
        {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
        <div className="flex gap-2">
          <Button type="button" onClick={() => void update()} disabled={working}>{working ? "در حال ذخیره…" : "ذخیره و انتخاب"}</Button>
          <Button type="button" variant="outline" onClick={() => modal.current?.close()} disabled={working}>انصراف</Button>
        </div>
      </div>
    </dialog>
  </div>;
}
