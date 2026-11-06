"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronsUpDown, Store, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { selectStoreContext, saveDefaultStore } from "@/app/(console)/store-context/actions";
import { confirmWorkflowNavigation } from "@/lib/workflows/navigation";
import type { StoreContextSnapshot } from "@/lib/store-context";

interface Props { context: StoreContextSnapshot }

/** Odoo-style multi-selection with one current Store per browser session. */
export function StoreSwitcher({ context }: Props) {
  const key = `${context.version}:${context.current_store_id}:${context.active_store_ids.join(",")}`;
  return <StoreSwitcherForm key={key} context={context} />;
}

/** A verified context refresh resets the draft without a cascading effect. */
function StoreSwitcherForm({ context }: Props) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [selection, setSelection] = useState(context.active_store_ids);
  const [current, setCurrent] = useState(context.current_store_id);
  const [notice, setNotice] = useState("");
  const [busy, startTransition] = useTransition();



  const active = useMemo(() =>
    context.stores.find((item) => item.id === context.current_store_id),
    [context],
  );

  function toggle(id: string) {
    if (busy) return;
    setNotice("");
    if (selection.includes(id)) {
      if (selection.length === 1) {
        setNotice("حداقل یک فروشگاه را انتخاب کنید.");
        return;
      }
      const next = selection.filter((item) => item !== id);
      setSelection(next);
      if (current === id) setCurrent(next[0]);
    } else {
      setSelection([...selection, id]);
    }
  }

  function chooseCurrent(id: string) {
    if (busy) return;
    setNotice("");
    setCurrent(id);
    setSelection((old) => old.includes(id) ? old : [...old, id]);
  }

  function applySelection() {
    if (busy || !confirmWorkflowNavigation()) return;
    startTransition(async () => {
      const result = await selectStoreContext({
        expected_version: context.version,
        current_store_id: current,
        active_store_ids: selection,
      });
      if (!result.ok) {
        setNotice(result.message);
        return;
      }
      setNotice("");
      setOpen(false);
      router.refresh();
    });
  }

  function setDefault() {
    if (busy || !confirmWorkflowNavigation()) return;
    startTransition(async () => {
      const result = await saveDefaultStore(
        context.current_store_id, context.preference_version,
      );
      setNotice(result.ok ? "فروشگاه پیش‌فرض ذخیره شد." : result.message);
      if (result.ok) router.refresh();
    });
  }

  return <div className="relative min-w-0" dir="rtl">
    <button type="button" disabled={busy}
      aria-haspopup="dialog" aria-expanded={open}
      aria-label="انتخاب یک یا چند فروشگاه فعال"
      onClick={() => setOpen(!open)}
      className="flex h-10 min-w-0 max-w-52 items-center gap-2 rounded-lg border border-border bg-background px-3 text-sm hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring sm:max-w-64">
      <Store className="size-4 shrink-0" aria-hidden="true" />
      <span className="truncate font-medium">{active?.name ?? "فروشگاه"}</span>
      {context.active_store_ids.length > 1 ?
        <span className="rounded bg-muted px-1.5 text-xs" aria-label="تعداد فروشگاه‌های فعال">
          {context.active_store_ids.length}
        </span> : null}
      <ChevronsUpDown className="size-4 shrink-0 opacity-60" aria-hidden="true" />
    </button>
    <Dialog open={open} onClose={() => setOpen(false)} label="انتخاب فروشگاه">
      <div className="space-y-4 p-5">
      <div>
        <p className="text-sm font-semibold">فروشگاه‌های مجاز من</p>
        <p className="mt-1 text-xs leading-6 text-muted-foreground">
          فروشگاه‌های قابل مشاهده را انتخاب کنید. تغییرات در فروشگاه «جاری» ثبت می‌شوند.
        </p>
      </div>
      <div className="max-h-72 space-y-2 overflow-y-auto">
        {context.stores.map((store) => <div key={store.id}
          className="flex items-center gap-3 rounded-lg border p-2 text-sm">
          <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
            <input type="checkbox" disabled={busy} checked={selection.includes(store.id)}
              onChange={() => toggle(store.id)} aria-label={`فعال‌سازی ${store.name}`} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{store.name}</span>
              <span className="text-xs text-muted-foreground">
                {({ owner: "مالک", manager: "مدیر", editor: "ویرایشگر", viewer: "مشاهده‌گر" } as Record<string, string>)[store.access_level] ?? store.access_level} · {({ active: "فعال", paused: "متوقف", archived: "بایگانی" } as Record<string, string>)[store.state] ?? store.state}
              </span>
            </span>
          </label>
          <label title="فروشگاه جاری برای ثبت تغییرات" className="flex items-center gap-1 text-xs">
            <input type="radio" name="current-store" disabled={busy}
              aria-label={`انتخاب ${store.name} برای ثبت تغییرات`}
              checked={current === store.id}
              onChange={() => chooseCurrent(store.id)} />
            <span>{current === store.id ? "جاری" : "انتخاب"}</span>
          </label>
        </div>)}
      </div>
      {notice ? <p role="status" className="text-xs leading-6 text-destructive">{notice}</p> : null}
      <div className="flex gap-2">
        <Button size="sm" onClick={applySelection} disabled={busy}>
          <Check className="size-4" /> اعمال انتخاب
        </Button>
        <Button size="sm" variant="outline" disabled={busy}
          onClick={() => setOpen(false)}>بستن</Button>
      </div>
      <div className="border-t pt-3">
        <button type="button" disabled={busy} onClick={setDefault}
          className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground">
          <Star className="size-4" />
          {context.current_store_id === context.default_store_id
            ? "این فروشگاه پیش‌فرض شماست"
            : "ذخیرهٔ فروشگاه جاری به‌عنوان پیش‌فرض"}
        </button>
      </div>
      </div>
    </Dialog>
  </div>;
}
