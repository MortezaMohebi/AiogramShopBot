"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronDown, Filter, Layers3, Search, Star, X } from "lucide-react";
import {
  createContext, useContext, useEffect, useId, useRef, useState, useSyncExternalStore,
  type ReactNode,
} from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const Scope = createContext("");
const storageEvent = "dashboard-saved-searches";

export function SearchPreferenceScope({ scope, children }: { scope: string; children: ReactNode }) {
  return <Scope.Provider value={scope}>{children}</Scope.Provider>;
}

/** A native disclosure keeps GET fields in their form and supports keyboard and touch. */
export function SearchTools({ main, filters, groups, favorites }: {
  main?: ReactNode;
  filters?: ReactNode;
  groups?: ReactNode;
  favorites: ReactNode;
}) {
  const details = useRef<HTMLDetailsElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const id = useId();

  useEffect(() => {
    function closeOutside(event: PointerEvent) {
      if (!details.current?.open || !(event.target instanceof Element)) return;
      // The Persian date picker renders its calendar in a React Aria portal.
      if (bar.current?.contains(event.target) || event.target.closest("[data-trigger][data-placement], [data-testid=underlay]")) return;
      details.current.open = false;
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented || !details.current?.open ||
          document.querySelector("[data-trigger][data-placement]")) return;
      event.preventDefault();
      details.current.open = false;
      details.current.querySelector("summary")?.focus();
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  return <div ref={bar} className="relative flex w-full min-w-0 max-w-4xl items-center gap-2">
    {main}
    <details ref={details} className="group/search min-w-0 shrink-0">
      <summary aria-controls={id}
        className="flex h-10 cursor-pointer list-none items-center gap-2 rounded-md border border-input bg-background px-3 text-sm font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring [&::-webkit-details-marker]:hidden">
        <Filter aria-hidden className="size-4" />
        <span>فیلترها و نماها</span>
        <ChevronDown aria-hidden className="size-4 group-open/search:rotate-180" />
      </summary>
      <div id={id} className={cn(
        "absolute inset-x-0 top-full z-30 mt-2 grid max-h-[min(65vh,32rem)] overflow-y-auto rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg",
        filters && groups ? "gap-4 md:grid-cols-3" : (filters || groups) ? "gap-4 sm:grid-cols-2" : "max-w-xs",
      )}>
        {filters ? <SearchSection icon={<Filter />} title="فیلترها">{filters}</SearchSection> : null}
        {groups ? <SearchSection icon={<Layers3 />} title="گروه‌بندی" divided={!!filters}>{groups}</SearchSection> : null}
        <SearchSection icon={<Star />} title="علاقه‌مندی‌ها" divided={!!(filters || groups)}>{favorites}</SearchSection>
      </div>
    </details>
  </div>;
}

function SearchSection({ icon, title, children, divided }: {
  icon: ReactNode; title: string; children: ReactNode; divided?: boolean;
}) {
  return <section className={cn("min-w-0 space-y-3", divided && "border-t pt-3 sm:border-s sm:border-t-0 sm:ps-4 sm:pt-0")}>
    <h2 className="flex items-center gap-2 text-sm font-semibold [&_svg]:size-4 [&_svg]:text-primary">{icon}{title}</h2>
    {children}
  </section>;
}

type Favorite = { name: string; value: unknown };

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(storageEvent, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(storageEvent, listener);
  };
}

export function SearchFavorites({ id, value, onRestore, disabled }: {
  id: string; value: unknown; onRestore: (value: unknown) => void; disabled?: boolean;
}) {
  const scope = useContext(Scope);
  const key = `dashboard-search:v1:${scope}:${id}`;
  const nameId = useId();
  const [name, setName] = useState("");
  const [issue, setIssue] = useState("");
  const saved = useSyncExternalStore(subscribe, () => {
    try { return scope ? localStorage.getItem(key) ?? "[]" : "[]"; }
    catch { return "[]"; }
  }, () => "[]");

  let items: Favorite[] = [];
  try {
    const parsed: unknown = JSON.parse(saved);
    if (Array.isArray(parsed)) {
      items = parsed.filter((item): item is Favorite => item && typeof item.name === "string" && item.name.length <= 64).slice(0, 12);
    }
  } catch { /* A corrupt entry can be replaced on the next save. */ }

  function write(next: Favorite[]) {
    if (!scope) return;
    try {
      localStorage.setItem(key, JSON.stringify(next));
      window.dispatchEvent(new Event(storageEvent));
      setIssue("");
    } catch {
      setIssue("ذخیره در این مرورگر ممکن نیست.");
    }
  }

  return <div className="space-y-3">
    {items.length ? <ul className="space-y-1">
      {items.map((item, index) => <li key={index} className="flex min-w-0 items-center gap-1">
        <Button type="button" variant="ghost" size="sm" className="min-w-0 flex-1 justify-start"
          disabled={disabled} onClick={() => onRestore(item.value)}>
          <span className="truncate">{item.name}</span>
        </Button>
        <Button type="button" variant="ghost" size="icon" aria-label={`حذف نمای ${item.name}`}
          disabled={disabled} onClick={() => write(items.filter((_, position) => position !== index))}><X /></Button>
      </li>)}
    </ul> : <p className="text-xs text-muted-foreground">هنوز نمایی ذخیره نشده است.</p>}
    <div className="space-y-2 border-t pt-3">
      <label className="text-xs font-medium" htmlFor={nameId}>نام نما</label>
      <Input id={nameId} value={name} maxLength={64} onChange={event => setName(event.target.value)}
        onKeyDown={event => { if (event.key === "Enter") event.preventDefault(); }} />
      <Button type="button" variant="outline" size="sm" disabled={disabled || !scope || !name.trim()}
        onClick={() => {
          const label = name.trim();
          write([{ name: label, value }, ...items.filter(item => item.name !== label)].slice(0, 12));
          setName("");
        }}>ذخیرهٔ نمای فعلی</Button>
    </div>
    {issue ? <p role="status" className="text-xs text-destructive">{issue}</p> : null}
  </div>;
}

type SearchValue = { label: string; value: string; display?: string; inactive?: string };
type ListSearchProps = {
  path: string;
  fixed?: Record<string, string>;
  query?: { name: string; label: string; value: string; placeholder?: string; dir?: "ltr" | "rtl" };
  values?: Record<string, SearchValue>;
  filters?: ReactNode;
  groups?: ReactNode;
};

export function ListSearch({ path, fixed = {}, query, values = {}, filters, groups }: ListSearchProps) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);
  const active = Object.entries(values).filter(([, item]) => item.value && item.value !== item.inactive);
  const current = Object.fromEntries(active.map(([name, item]) => [name, item.value]));
  if (query?.value) current[query.name] = query.value;
  const route = (state: Record<string, string>) => {
    const params = new URLSearchParams({ ...fixed, ...state }).toString();
    return params ? `${path}?${params}` : path;
  };
  const remove = (name: string) => route(Object.fromEntries(Object.entries(current).filter(([key]) => key !== name)));
  const viewId = `${path}?${new URLSearchParams(fixed)}`;
  const allowed = Object.keys(values);
  if (query) allowed.push(query.name);

  return <form ref={form} action={path} method="get" className="space-y-3" role="search" aria-label="جست‌وجوی فهرست">
    {Object.entries(fixed).map(([name, value]) => <input key={name} type="hidden" name={name} value={value} />)}
    <SearchTools main={query ? <div className="flex min-w-0 flex-1 gap-2">
      <Input key={query.value} type="search" name={query.name} aria-label={query.label}
        defaultValue={query.value} maxLength={100} dir={query.dir} placeholder={query.placeholder ?? "جست‌وجو…"} />
      <Button type="submit" variant="outline" size="icon" aria-label="جست‌وجو"><Search /></Button>
    </div> : null}
      filters={filters ? <div className="space-y-3" key={JSON.stringify(current)}>
        {filters}
        <Button type="submit" size="sm">اعمال فیلترها</Button>
      </div> : null}
      groups={groups}
      favorites={<SearchFavorites id={viewId} value={current} onRestore={value => {
        if (!value || typeof value !== "object") return;
        const fields = value as Record<string, unknown>;
        const restored = Object.fromEntries(allowed.flatMap(name =>
          typeof fields[name] === "string" && fields[name].length <= 200 ? [[name, fields[name]]] : []));
        const details = form.current?.querySelector("details");
        if (details) details.open = false;
        router.push(route(restored));
      }} />} />
    {active.length ? <div className="flex flex-wrap items-center gap-2" aria-label="فیلترهای فعال">
      {active.map(([name, item]) => <Link key={name} href={remove(name)}
        className="inline-flex max-w-full items-center gap-1 rounded-md border bg-muted/40 px-2 py-1.5 text-xs hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
        aria-label={`حذف فیلتر ${item.label}`}>
        <span className="break-all">{item.label} · <bdi>{item.display ?? item.value}</bdi></span><X aria-hidden className="size-3 shrink-0" />
      </Link>)}
      <Link href={route({})} className="text-xs text-primary underline underline-offset-4">پاک‌کردن فیلترها</Link>
    </div> : null}
  </form>;
}
