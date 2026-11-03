"use client";

import { type KeyboardEvent, useId, useMemo, useRef, useState } from "react";
import { Check, LoaderCircle, Pencil, Plus, Search, X } from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import type { Category } from "@/lib/types";

interface Props {
  categories: Category[];
  initialId?: number | null;
  canCreate?: boolean;
}

const normalized = (value: string) => value.normalize("NFKC").trim().toLocaleLowerCase();

/**
 * Odoo-like many2one picker: search by name, select an ID, quick-create
 * a draft only for authorized editors. Never submit arbitrary typed text.
 */
export function CategoryMany2One({
  categories,
  initialId = null,
  canCreate = true,
}: Props) {
  const id = useId();
  const [options, setOptions] = useState(categories);
  const selected = categories.find((option) => option.id === initialId);
  const [value, setValue] = useState(selected?.name ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(initialId);
  const [expanded, setExpanded] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const [editName, setEditName] = useState("");
  const [updating, setUpdating] = useState(false);

  const matching = useMemo(
    () => options.filter(
      (option) => normalized(option.name).includes(normalized(value)),
    ).slice(0, 30),
    [options, value],
  );
  const isExact = options.some(
    (option) => normalized(option.name) === normalized(value),
  );

  function choose(option: Category) {
    setValue(option.name);
    setSelectedId(option.id);
    setExpanded(false);
    setError(null);
  }

  async function create() {
    if (!canCreate || creating || !value.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/categories", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ name: value.trim() }),
        signal: AbortSignal.timeout(15_000),
      });
      if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
        throw new Error("پاسخ سرویس معتبر نیست.");
      }
      const result = await response.json() as {
        ok?: boolean; id?: number; name?: string; code?: string;
      };
      if (!response.ok || !result.ok || !Number.isSafeInteger(result.id)) {
        throw new Error(
          result.code === "already_exists"
            ? "این دسته‌بندی قبلاً ثبت شده است."
            : result.code === "permission_denied"
              ? "اجازهٔ ساخت دسته‌بندی ندارید."
              : "ایجاد دسته‌بندی انجام نشد.",
        );
      }
      const record: Category = {
        id: result.id!,
        name: result.name ?? value.trim(),
        position: 0,
        is_published: false,
      };
      setOptions((previous) => [...previous, record]);
      choose(record);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ارتباط برقرار نشد.");
    } finally {
      setCreating(false);
    }
  }

  function beginEdit() {
    const selected = options.find((option) => option.id === selectedId);
    if (!selected) return;
    setEditName(selected.name);
    setError(null);
    setExpanded(false);
    dialog.current?.showModal();
  }

  /** Edit exactly the selected database record, preserving the hidden ID. */
  async function saveEdit() {
    const name = editName.trim();
    if (selectedId === null || !name || name.length > 255 || updating) {
      setError("نام دسته‌بندی معتبر نیست.");
      return;
    }
    setUpdating(true);
    setError(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/categories", {
        method: "PATCH",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: JSON.stringify({ id: selectedId, name }),
        signal: AbortSignal.timeout(15_000),
      });
      const result = await response.json() as {
        ok?: boolean; id?: number; name?: string; code?: string;
      };
      if (!response.ok || !result.ok || result.id !== selectedId) {
        throw new Error(result.code === "already_exists"
          ? "این نام قبلاً ثبت شده است."
          : result.code === "permission_denied"
            ? "مجوز ویرایش این دسته‌بندی را ندارید."
            : "ویرایش دسته‌بندی انجام نشد.");
      }
      setOptions((previous) => previous.map((item) =>
        item.id === selectedId ? { ...item, name } : item
      ));
      setValue(name);
      dialog.current?.close();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "ارتباط با سرور برقرار نشد.");
    } finally {
      setUpdating(false);
    }
  }

  function keyboard(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setExpanded(false);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setExpanded(true);
      setHighlight((index) => Math.min(index + 1, matching.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((index) => Math.max(0, index - 1));
    } else if (event.key === "Enter" && expanded && matching.length) {
      event.preventDefault();
      choose(matching[Math.max(0, highlight)]);
    }
  }

  return (
    <div
      className="relative space-y-2"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setExpanded(false);
          if (selectedId === null) setValue("");
        }
      }}
    >
      <input type="hidden" name="category_id" value={selectedId ?? ""} />
      <div className="relative flex items-center gap-1">
        <Search aria-hidden="true" className="absolute start-3 size-4 text-muted-foreground" />
        <input
          id={id}
          role="combobox"
          aria-label="جست‌وجو و انتخاب دسته‌بندی"
          aria-autocomplete="list"
          aria-controls={id + "-list"}
          aria-expanded={expanded}
          aria-activedescendant={
            expanded && matching.length ? id + "-option-" + highlight : undefined
          }
          autoComplete="off"
          value={value}
          maxLength={255}
          onChange={(event) => {
            setValue(event.target.value);
            setSelectedId(null);
            setHighlight(0);
            setExpanded(true);
          }}
          onFocus={() => setExpanded(true)}
          onKeyDown={keyboard}
          placeholder="جست‌وجوی دسته‌بندی..."
          className="h-10 w-full rounded-md border border-input bg-background ps-10 pe-9 text-sm outline-none focus-visible:outline-2 focus-visible:outline-ring"
        />
        {selectedId !== null ? (
          <button
            type="button"
            aria-label="پاک‌کردن دسته‌بندی"
            onClick={() => {
              setValue("");
              setSelectedId(null);
            }}
            className="absolute end-2 rounded p-1 text-muted-foreground hover:text-foreground"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        ) : null}
      </div>
      {expanded ? (
        <div
          id={id + "-list"}
          role="listbox"
          aria-label="دسته‌بندی‌های موجود"
          className="absolute z-30 max-h-64 w-full overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-xl"
        >
          {matching.map((option, index) => (
            <button
              id={id + "-option-" + index}
              role="option"
              aria-selected={option.id === selectedId}
              key={option.id}
              type="button"
              onClick={() => choose(option)}
              className={
                "flex w-full items-center justify-between rounded px-3 py-2 text-start text-sm hover:bg-accent " +
                (highlight === index ? "bg-muted" : "")
              }
            >
              <span>{option.name}</span>
              {option.id === selectedId ? <Check aria-hidden="true" className="size-4" /> : null}
            </button>
          ))}
          {matching.length === 0 ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">نتیجه‌ای پیدا نشد.</p>
          ) : null}
          {canCreate && value.trim() && !isExact ? (
            <button
              type="button"
              disabled={creating}
              onClick={() => void create()}
              className="flex w-full items-center gap-2 rounded border-t px-3 py-2 text-start text-sm text-primary hover:bg-accent disabled:opacity-50"
            >
              {creating
                ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                : <Plus aria-hidden="true" className="size-4" />}
              ایجاد دسته‌بندی «{value.trim()}» به‌صورت پیش‌نویس
            </button>
          ) : null}
        </div>
      ) : null}
      {selectedId !== null && canCreate ? (
        <button type="button" onClick={beginEdit}
          className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-2 text-xs text-foreground hover:bg-accent">
          <Pencil aria-hidden="true" className="size-4" />
          ویرایش دسته‌بندی انتخاب‌شده
        </button>
      ) : null}
      {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
      <p className="text-xs text-muted-foreground">
        انتخاب اختیاری است؛ دسته‌بندی جدید ابتدا منتشرنشده می‌ماند.
      </p>
      <dialog ref={dialog}
        className="m-auto w-[min(94vw,28rem)] rounded-xl border border-border bg-card p-0 text-card-foreground shadow-2xl backdrop:bg-black/60"
        onClose={() => setError(null)}>
        <div dir="rtl" className="space-y-4 p-6">
          <p className="text-xs text-muted-foreground">محصول / دسته‌بندی / ویرایش</p>
          <h2 className="text-lg font-semibold">ویرایش دسته‌بندی</h2>
          <label className="block space-y-2 text-sm">
            نام دسته‌بندی
            <input value={editName} autoFocus maxLength={255}
              onChange={(event) => setEditName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void saveEdit();
                }
              }}
              className="h-10 w-full rounded-md border border-input bg-background px-3" />
          </label>
          {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
          <div className="flex gap-2">
            <button type="button" disabled={updating} onClick={() => void saveEdit()}
              className="h-10 rounded-md bg-primary px-4 text-sm text-primary-foreground disabled:opacity-50">
              {updating ? "در حال ذخیره..." : "ذخیره دسته‌بندی"}
            </button>
            <button type="button" disabled={updating} onClick={() => dialog.current?.close()}
              className="h-10 rounded-md border border-border px-4 text-sm">انصراف</button>
          </div>
        </div>
      </dialog>
    </div>
  );
}
