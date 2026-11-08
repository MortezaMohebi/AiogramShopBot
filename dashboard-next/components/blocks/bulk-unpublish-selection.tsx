"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

type Entity = "products" | "categories";
type SelectionContext = {
  selected: Set<number>;
  eligible: number[];
  toggle: (id: number, checked: boolean) => void;
  toggleAll: (checked: boolean) => void;
};

const Context = createContext<SelectionContext | null>(null);
const errorMessages: Record<string, string> = {
  security_check_failed: "بررسی امنیتی ناموفق بود؛ صفحه را تازه‌سازی کنید.",
  session_expired: "نشست مدیریت پایان یافته است؛ دوباره وارد شوید.",
  permission_denied: "مجوز بایگانی این موارد را ندارید.",
  selection_changed: "فهرست تغییر کرده است؛ صفحه را تازه‌سازی و دوباره انتخاب کنید.",
  invalid_request: "انتخاب معتبر نیست؛ صفحه را تازه‌سازی کنید.",
  service_unavailable: "نتیجهٔ عملیات مشخص نیست؛ وضعیت فهرست را بررسی کنید.",
};

/** Select published rows on this view and ask before hiding them from customers. */
export function BulkUnpublishSelection({ entity, eligible, children, enabled = true, canArchive = true,
  archivable = eligible }: {
  entity: Entity; eligible: number[]; children: ReactNode; enabled?: boolean;
  canArchive?: boolean; archivable?: number[];
}) {
  const router = useRouter();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; message: string }>();
  const noun = entity === "products" ? "محصول" : "دسته‌بندی";
  const visibleSelected = eligible.filter((id) => selected.has(id));
  const archiveSelected = archivable.filter((id) => selected.has(id));

  function toggle(id: number, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(eligible) : new Set());
  }

  async function apply() {
    if (busy || archiveSelected.length === 0) return;
    setBusy(true);
    setNotice(undefined);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/bulk-unpublish", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        redirect: "error", signal: AbortSignal.timeout(25_000),
        headers: {
          "Content-Type": "application/json", Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ entity, ids: archiveSelected }),
      });
      const result = await response.json() as {
        ok?: boolean; code?: string; unpublished?: number;
      };
      if (!response.ok || !result.ok) {
        setNotice({ ok: false, message: errorMessages[result.code ?? ""] ?? errorMessages.service_unavailable });
        return;
      }
      setOpen(false);
      setSelected(new Set());
      setNotice({ ok: true, message: `${result.unpublished ?? archiveSelected.length} ${noun} از نمایش به مشتری برداشته شد.` });
      router.refresh();
    } catch {
      setNotice({ ok: false, message: errorMessages.service_unavailable });
    } finally {
      setBusy(false);
    }
  }

  if (!enabled) return <>{children}</>;
  return <Context.Provider value={{ selected, eligible, toggle, toggleAll }}>
    <div className="mb-4 flex flex-wrap items-center gap-3">
      {canArchive ? <Button type="button" variant="outline" size="sm" disabled={!archiveSelected.length}
        onClick={() => { setNotice(undefined); setOpen(true); }}>
        بایگانی انتخاب‌شده‌ها ({archiveSelected.length})
      </Button> : null}
      {entity === "products" && visibleSelected.length ? <Button asChild variant="outline" size="sm">
        <Link href={`/data-models/products?ids=${visibleSelected.join(",")}`}>خروجی انتخاب‌شده‌ها ({visibleSelected.length})</Link>
      </Button> : null}
      <span className="text-xs text-muted-foreground">انتخاب همه فقط سطرهای همین صفحه را شامل می‌شود.</span>
    </div>
    {notice && !open ? <p role={notice.ok ? "status" : "alert"}
      className={`mb-4 rounded-md p-3 text-sm ${notice.ok ? "bg-accent text-accent-foreground" : "bg-destructive/10 text-destructive"}`}>
      {notice.message}
    </p> : null}
    {children}
    <Dialog open={open} label="تأیید بایگانی انتخاب‌شده‌ها" onClose={() => { if (!busy) setOpen(false); }}>
      <div className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">بایگانی {archiveSelected.length} {noun}</h2>
        <p className="text-sm leading-7">
          {entity === "products"
            ? "محصولات انتخاب‌شده از فروشگاه ربات‌ها پنهان می‌شوند. اطلاعات محصول و سوابق سفارش حفظ می‌شوند؛ می‌توانید آن‌ها را دوباره منتشر کنید."
            : "دسته‌بندی‌های انتخاب‌شده از منوی دسته‌بندی مشتری پنهان می‌شوند. محصولات و سوابق سفارش حذف نمی‌شوند؛ می‌توانید دسته‌بندی‌ها را دوباره منتشر کنید."}
        </p>
        {notice && !notice.ok ? <p role="alert" className="text-sm text-destructive">
          {notice.message}
        </p> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>انصراف</Button>
          <Button type="button" variant="destructive" disabled={busy} onClick={() => void apply()}>
            {busy ? "در حال ذخیره…" : "بایگانی موارد انتخاب‌شده"}
          </Button>
        </div>
      </div>
    </Dialog>
  </Context.Provider>;
}

/** A row checkbox or current-page select-all checkbox. */
export function BulkSelectCheckbox({ id, all = false }: { id?: number; all?: boolean }) {
  const state = useContext(Context);
  if (!state) return null;
  const checked = all
    ? state.eligible.length > 0 && state.eligible.every((value) => state.selected.has(value))
    : id !== undefined && state.selected.has(id);
  return <input type="checkbox" className="size-4 accent-primary" checked={checked}
    disabled={all ? !state.eligible.length : id === undefined || !state.eligible.includes(id)}
    aria-label={all ? "انتخاب همهٔ موارد منتشرشده در این فهرست" : `انتخاب مورد ${id}`}
    onClick={(event) => event.stopPropagation()}
    onChange={(event) => {
      if (all) state.toggleAll(event.target.checked);
      else if (id !== undefined) state.toggle(id, event.target.checked);
    }} />;
}
