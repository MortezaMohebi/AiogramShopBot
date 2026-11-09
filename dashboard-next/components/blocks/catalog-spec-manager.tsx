"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { CatalogSpecDialog } from "@/components/blocks/catalog-spec-dialog";
import { CatalogSpecPicker } from "@/components/blocks/catalog-spec-picker";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { catalogSpecError, deleteCatalogSpec, readCatalogSpecs, type CatalogKind, type CatalogPage, type CatalogSpec } from "@/lib/catalog-specs";

export function CatalogSpecManager({ storeId, kind }: { storeId: string; kind: CatalogKind }) {
  const attributes = kind === "attributes";
  const noun = attributes ? "ویژگی" : "مقدار";
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [parent, setParent] = useState<CatalogSpec>();
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: CatalogPage; error?: string }>();
  const [editor, setEditor] = useState<{ item?: CatalogSpec } | null>(null);
  const [removing, setRemoving] = useState<CatalogSpec | null>(null);
  const [pending, setPending] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [notice, setNotice] = useState("");
  const deleting = useRef(false);
  const parentId = parent?.id;
  const key = JSON.stringify([storeId, kind, query, page, parentId, revision]);
  const current = result?.key === key ? result : undefined;

  useEffect(() => {
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void readCatalogSpecs(storeId, kind, query, page, parentId, abort.signal).then(
        (data) => { if (!abort.signal.aborted) setResult({ key, data }); },
        (error: unknown) => { if (!abort.signal.aborted) setResult({ key, error: catalogSpecError(error) }); },
      );
    }, query ? 180 : 0);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [storeId, kind, query, page, parentId, key]);

  function filter(item?: CatalogSpec) { setParent(item); setPage(1); }

  async function remove() {
    if (!removing || deleting.current) return;
    deleting.current = true;
    setPending(true);
    setDeleteError("");
    try {
      await deleteCatalogSpec(storeId, kind, removing.id);
      if (current?.data?.items.length === 1 && page > 1) setPage(page - 1);
      setRevision((value) => value + 1);
      setNotice(`${noun} حذف شد.`);
      setRemoving(null);
    } catch (failure) {
      setDeleteError(catalogSpecError(failure));
    } finally {
      setPending(false);
      deleting.current = false;
    }
  }

  return <div className="space-y-4" dir="rtl">
    <div className="flex flex-wrap items-center gap-2">
      <Input aria-label={`جست‌وجوی ${noun}`} placeholder={`جست‌وجوی ${noun}…`} type="search" maxLength={80}
        className="w-full sm:w-64" value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} />
      {!attributes && <>
        <CatalogSpecPicker storeId={storeId} kind="attributes" label={parent?.label ?? "همهٔ ویژگی‌ها"} onSelect={filter} />
        {parent && <Button type="button" variant="ghost" size="sm" onClick={() => filter()}>پاک کردن فیلتر</Button>}
      </>}
      <Button type="button" className="ms-auto" onClick={() => setEditor({})}><Plus aria-hidden="true" /> {noun} جدید</Button>
    </div>
    <p role="status" className={notice ? "text-sm text-muted-foreground" : "sr-only"}>{notice}</p>
    <div className="overflow-x-auto rounded-xl border bg-card" aria-busy={!current}>
      <table className="w-full text-sm">
        <caption className="sr-only">{attributes ? "فهرست ویژگی‌ها" : "فهرست مقدارها"}</caption>
        <thead className="bg-muted text-muted-foreground">
          <tr className="text-start [&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
            <th scope="col" className="text-start">عنوان</th>
            <th scope="col" className="text-start">{attributes ? "واحد" : "ویژگی"}</th>
            <th scope="col" className="text-start">کاربرد</th>
            <th scope="col" className="text-center">عملیات</th>
          </tr>
        </thead>
        <tbody>
          {current?.data?.items.map((item) => <tr key={item.id} className="border-t [&>td]:px-3 [&>td]:py-1.5">
            <td><button type="button" className="min-h-8 text-start font-medium text-primary hover:underline"
              onClick={() => setEditor({ item })}><bdi>{item.label}</bdi></button></td>
            <td><bdi>{(attributes ? item.unit : item.attribute_label) || "—"}</bdi></td>
            <td className="text-muted-foreground">{item.used ? "در محصول استفاده شده" : "آزاد"}</td>
            <td><div className="flex justify-center gap-0.5">
              <Button type="button" size="icon" variant="ghost" className="size-8" aria-label={`ویرایش ${item.label}`}
                onClick={() => setEditor({ item })}><Pencil aria-hidden="true" /></Button>
              <Button type="button" size="icon" variant="ghost" className="size-8 text-destructive"
                aria-label={`حذف ${item.label}`} disabled={item.used} onClick={() => { setDeleteError(""); setRemoving(item); }}>
                <Trash2 aria-hidden="true" />
              </Button>
            </div></td>
          </tr>)}
          {!current?.data?.items.length && <tr><td colSpan={4} className="p-5 text-center">
            {current?.error ? <div role="alert" className="space-y-2 text-destructive">
              <p>{current.error}</p><Button type="button" variant="outline" onClick={() => setRevision((value) => value + 1)}>تلاش دوباره</Button>
            </div> : <p role="status" className="text-muted-foreground">{current ? "موردی پیدا نشد." : "در حال دریافت فهرست…"}</p>}
          </td></tr>}
        </tbody>
      </table>
    </div>
    {(page > 1 || current?.data?.has_more) && <nav aria-label="صفحه‌بندی" className="flex items-center gap-2">
      <Button type="button" variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>قبلی</Button>
      <span className="text-sm text-muted-foreground">صفحهٔ {page.toLocaleString("fa-IR")}</span>
      <Button type="button" variant="outline" size="sm" disabled={!current?.data?.has_more || page >= 10000}
        onClick={() => setPage(page + 1)}>بعدی</Button>
    </nav>}
    {editor && <CatalogSpecDialog storeId={storeId} kind={kind} item={editor.item} parent={parent}
      onClose={() => setEditor(null)} onSaved={() => {
        setEditor(null);
        setRevision((value) => value + 1);
        setNotice(`${noun} ذخیره شد.`);
      }} />}
    {removing && <Dialog open label={`حذف ${noun}`} onClose={() => { if (!deleting.current) setRemoving(null); }}>
      <div className="space-y-3 p-5" dir="rtl">
        <h2 className="text-lg font-semibold">حذف <bdi>{removing.label}</bdi></h2>
        <p className="text-sm text-muted-foreground">{attributes
          ? "این ویژگی و مقدارهای استفاده‌نشدهٔ آن از فهرست فروشگاه حذف می‌شوند."
          : "این مقدار از فهرست فروشگاه حذف می‌شود."}</p>
        {deleteError && <p role="alert" className="text-sm text-destructive">{deleteError}</p>}
        <div className="flex gap-2">
          <Button type="button" variant="outline" disabled={pending} onClick={() => setRemoving(null)}>انصراف</Button>
          <Button type="button" variant="destructive" disabled={pending} onClick={() => void remove()}>حذف</Button>
        </div>
      </div>
    </Dialog>}
  </div>;
}
