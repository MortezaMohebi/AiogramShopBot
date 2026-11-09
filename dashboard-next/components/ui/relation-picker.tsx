"use client";

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Plus, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type RelationOption = { id: string | number; label: string; detail?: string };
export type RelationPage<T> = { items: T[]; has_more: boolean };

type Props<T extends RelationOption> = {
  label: string;
  sourceKey: string;
  load: (query: string, page: number, signal: AbortSignal) => Promise<RelationPage<T>>;
  errorMessage?: (error: unknown) => string;
  exclude?: T["id"][];
  onSelect: (item: T) => void;
  onCreate?: (query: string) => void;
  createLabel?: string;
  contained?: boolean;
  id?: string;
  disabled?: boolean;
  maxLength?: number;
};

const defaultError = (error: unknown) => error instanceof Error
  ? error.message : "دریافت فهرست انجام نشد.";

export function RelationPicker<T extends RelationOption>({
  label, sourceKey, load, errorMessage = defaultError, exclude, onSelect,
  onCreate, createLabel = "افزودن مورد جدید", contained, id, disabled, maxLength = 80,
}: Props<T>) {
  const listId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<CSSProperties | null>(null);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [active, setActive] = useState(-1);
  const [result, setResult] = useState<{ key: string; data?: RelationPage<T>; error?: string }>();
  const open = position !== null;
  const key = JSON.stringify([sourceKey, query, page]);
  const visible = result?.key === key ? result : undefined;
  const items = visible?.data?.items.filter((item) => !exclude?.includes(item.id)) ?? [];

  function close(restore = false) {
    setPosition(null);
    if (restore) trigger.current?.focus();
  }

  const positionForTrigger = useCallback((): CSSProperties | null => {
    const rect = trigger.current?.getBoundingClientRect();
    if (!rect || rect.bottom < 0 || rect.top > window.innerHeight) return null;
    if (contained) return {};
    const width = Math.min(Math.max(275, rect.width), window.innerWidth - 24);
    const above = rect.bottom + 300 > window.innerHeight && rect.top > window.innerHeight - rect.bottom;
    return {
      width, left: Math.min(Math.max(12, rect.right - width), window.innerWidth - width - 12),
      ...(above ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
      maxHeight: Math.max(100, Math.min(320, (above ? rect.top : window.innerHeight - rect.bottom) - 16)),
    };
  }, [contained]);

  function toggle() {
    if (open) { close(); return; }
    const next = positionForTrigger();
    if (!next) return;
    setPosition(next);
    setResult(undefined);
    setQuery("");
    setPage(1);
    setActive(-1);
  }

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void load(query, page, abort.signal).then(
        (data) => { if (!abort.signal.aborted) setResult({ key, data }); },
        (error: unknown) => { if (!abort.signal.aborted) setResult({ key, error: errorMessage(error) }); },
      );
    }, query ? 180 : 0);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [open, load, query, page, key, errorMessage]);

  useEffect(() => {
    if (!open) return;
    function dismiss(event: Event) {
      if (event.target instanceof Node
        && (panel.current?.contains(event.target) || trigger.current?.contains(event.target))) return;
      setPosition(null);
    }
    function reposition(event: Event) {
      if (event.target instanceof Node && panel.current?.contains(event.target)) return;
      setPosition(positionForTrigger());
    }
    panel.current?.querySelector("input")?.focus({ preventScroll: true });
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("focusin", dismiss);
    if (!contained) {
      document.addEventListener("scroll", reposition, true);
      window.addEventListener("resize", reposition);
    }
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("focusin", dismiss);
      document.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open, contained, positionForTrigger]);

  function pick(item: T) {
    close(true);
    onSelect(item);
  }

  function turn(next: number) { setPage(next); setActive(-1); }

  const dropdown = open && <div ref={panel} style={position} dir="rtl"
    className={`${contained ? "mt-1" : "fixed z-[70] overflow-auto"} rounded-md border bg-popover p-2 shadow-lg`}
    onKeyDown={(event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    }}>
    <Input role="combobox" aria-label={label} aria-expanded="true" aria-autocomplete="list"
      aria-controls={listId} aria-activedescendant={items[active] ? `${listId}-${items[active].id}` : undefined}
      value={query} placeholder="برای جست‌وجو تایپ کنید…" maxLength={maxLength}
      onChange={(event) => { setQuery(event.target.value); turn(1); }}
      onKeyDown={(event) => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Enter") {
          event.preventDefault();
          if (items[active] ?? items[0]) pick(items[active] ?? items[0]);
        } else if (items.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          event.preventDefault();
          const next = event.key === "ArrowDown" ? (active + 1) % items.length : active <= 0 ? items.length - 1 : active - 1;
          setActive(next);
          document.getElementById(`${listId}-${items[next].id}`)?.scrollIntoView({ block: "nearest" });
        }
      }} />
    <div id={listId} role="listbox" aria-label={label} className="mt-1 max-h-44 overflow-auto">
      {items.map((item, index) => <div key={item.id} id={`${listId}-${item.id}`} role="option"
        aria-selected={index === active} onMouseDown={(event) => event.preventDefault()} onClick={() => pick(item)}
        className="cursor-pointer rounded px-2 py-1.5 text-sm hover:bg-accent aria-selected:bg-accent">
        <bdi>{item.label}</bdi>{item.detail ? <small className="ms-2 text-muted-foreground"><bdi>{item.detail}</bdi></small> : null}
      </div>)}
    </div>
    {!visible ? <p role="status" className="p-2 text-sm text-muted-foreground">در حال جست‌وجو…</p>
      : visible.error ? <p role="alert" className="p-2 text-sm text-destructive">{visible.error}</p>
      : items.length === 0 ? <p role="status" className="p-2 text-sm text-muted-foreground">موردی برای انتخاب نیست.</p> : null}
    <div className="flex flex-wrap gap-1">
      {page > 1 && <Button type="button" size="sm" variant="ghost" onClick={() => {
        turn(page - 1); panel.current?.querySelector("input")?.focus();
      }}>قبلی</Button>}
      {visible?.data?.has_more && page < 10000 && <Button type="button" size="sm" variant="ghost" onClick={() => {
        turn(page + 1); panel.current?.querySelector("input")?.focus();
      }}>نتایج بیشتر</Button>}
      {onCreate && <Button type="button" size="sm" variant="ghost" className="text-primary" onClick={() => {
        close(true); onCreate(query.trim());
      }}><Plus aria-hidden="true" />{createLabel}</Button>}
    </div>
  </div>;

  return <>
    <Button ref={trigger} id={id} type="button" variant="ghost" size="sm" aria-expanded={open}
      disabled={disabled} onClick={toggle} className="max-w-full justify-start text-primary">
      <Search aria-hidden="true" /><span className="truncate">{label}</span><ChevronDown aria-hidden="true" />
    </Button>
    {dropdown && (contained ? dropdown : createPortal(dropdown, document.body))}
  </>;
}
