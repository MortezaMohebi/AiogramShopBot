"use client";

import { useRef, useState, type FormEvent } from "react";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SectionSearch<Filter extends string>({
  field, value, filter, choices, disabled, onSearch, onFilter,
}: {
  field: string;
  value: string;
  filter: Filter | null;
  choices: { value: Filter; label: string }[];
  disabled: boolean;
  onSearch: (value: string) => void;
  onFilter: (value: Filter | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const filters = useRef<HTMLDetailsElement>(null);
  const [draft, setDraft] = useState({ source: value, text: "" });
  const text = draft.source === value ? draft.text : "";
  const needle = text.trim();
  const selectedFilter = choices.find(choice => choice.value === filter);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || !needle) return;
    setDraft({ source: value, text: "" });
    onSearch(needle);
    input.current?.focus({ preventScroll: true });
  }

  return <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2">
    {value ? <Button type="button" size="sm" variant="secondary" disabled={disabled}
      className="h-auto min-h-8 max-w-full whitespace-normal break-all"
      aria-label={`حذف فیلتر ${field}`} onClick={() => {
        onSearch("");
        input.current?.focus({ preventScroll: true });
      }}>
      {field} شامل «{value}» <X aria-hidden="true" className="size-3" />
    </Button> : null}
    {selectedFilter ? <Button type="button" size="sm" variant="secondary" disabled={disabled}
      aria-label={`حذف فیلتر ${selectedFilter.label}`} onClick={() => {
        onFilter(null);
        input.current?.focus({ preventScroll: true });
      }}>
      {selectedFilter.label} <X aria-hidden="true" className="size-3" />
    </Button> : null}
    <form onSubmit={submit} role="search" className="relative flex min-w-36 flex-1 items-center gap-2">
      <Search aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
      <Input ref={input} type="search" className="h-9 min-w-0"
        aria-label={`جست‌وجوی ${field}`} placeholder={`جست‌وجوی ${field}…`}
        value={text} onChange={event => setDraft({ source: value, text: event.target.value })}
        onKeyDown={event => { if (event.key === "Escape") setDraft({ source: value, text: "" }); }}
        maxLength={100} autoComplete="off" disabled={disabled} />
      {needle && !disabled ? <div className="absolute inset-x-0 top-full z-20 mt-2 rounded-md border bg-popover p-1 shadow">
        <Button type="submit" variant="ghost" className="h-auto w-full justify-start whitespace-normal break-all text-start">
          {field} شامل «{needle}»
        </Button>
      </div> : null}
    </form>
    <details ref={filters} className="relative">
      <summary aria-disabled={disabled} onClick={event => { if (disabled) event.preventDefault(); }}
        className="flex cursor-pointer list-none items-center gap-2 rounded-md border px-3 py-2 text-sm focus-visible:outline [&::-webkit-details-marker]:hidden">
        <SlidersHorizontal aria-hidden="true" className="size-4" /> فیلترها
      </summary>
      <div className="absolute end-0 top-full z-20 mt-2 min-w-36 rounded-md border bg-popover p-1 shadow">
        {choices.map(choice => <Button type="button" key={choice.value} size="sm" variant="ghost"
          className="w-full justify-start" disabled={disabled} aria-pressed={choice.value === filter}
          onClick={() => {
            onFilter(choice.value === filter ? null : choice.value);
            if (filters.current) filters.current.open = false;
            input.current?.focus({ preventScroll: true });
          }}>{choice.label}</Button>)}
      </div>
    </details>
  </div>;
}
