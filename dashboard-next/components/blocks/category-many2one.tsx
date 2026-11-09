"use client";

import { useMemo, useState } from "react";
import { Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LocalRelationPicker } from "@/components/ui/local-relation-picker";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Dialog } from "@/components/ui/dialog";
import { categoryPath } from "@/lib/category-tree";
import type { Category } from "@/lib/types";

interface Props {
  categories: Category[];
  initialId?: number | null;
  canCreate?: boolean;
  onSelectionChange?: () => void;
}

const CHALLENGE_ERRORS: Record<string, string> = {
  security_check_failed: "بررسی نشست انجام نشد. صفحه را تازه‌سازی کنید.",
  service_unavailable: "سرویس دسته‌بندی در دسترس نیست.",
  network_unavailable: "ارتباط با سرویس دسته‌بندی برقرار نشد.",
};

/** A transport failure does not establish whether the category was saved. */
function categoryError(error: unknown): string {
  if (error instanceof Error) {
    if (Object.hasOwn(CHALLENGE_ERRORS, error.message)) return CHALLENGE_ERRORS[error.message];
    if (error.name === "Error") return error.message;
  }
  return "نتیجهٔ ذخیرهٔ دسته‌بندی مشخص نشد. پیش از تکرار، وضعیت دسته‌بندی را بررسی کنید.";
}

/**
 * Odoo-like many2one picker: search by name, select an ID, quick-create
 * a draft only for authorized editors. Never submit arbitrary typed text.
 */
export function CategoryMany2One({
  categories,
  initialId = null,
  canCreate = true,
  onSelectionChange,
}: Props) {
  const [options, setOptions] = useState(categories);
  const [selectedId, setSelectedId] = useState<number | null>(initialId);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [updating, setUpdating] = useState(false);
  const selected = options.find((option) => option.id === selectedId);
  const choices = useMemo(() => {
    const byId = new Map(options.map(item => [item.id, item]));
    return options.map(item => ({ id: item.id, label: categoryPath(item, byId) }));
  }, [options]);

  function choose(id: number | null) {
    if (id !== selectedId) onSelectionChange?.();
    setSelectedId(id);
    setError(null);
  }

  async function create(value: string) {
    if (!canCreate || creating) return;
    if (!value.trim()) { setError("برای تعریف دسته‌بندی، نام آن را در جست‌وجو بنویسید."); return; }
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
      choose(record.id);
    } catch (cause) {
      setError(categoryError(cause));
    } finally {
      setCreating(false);
    }
  }

  function beginEdit() {
    const selected = options.find((option) => option.id === selectedId);
    if (!selected) return;
    setEditName(selected.name);
    setError(null);
    setEditing(true);
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
      setEditing(false);
    } catch (cause) {
      setError(categoryError(cause));
    } finally {
      setUpdating(false);
    }
  }

  return (
    <div className="space-y-2">
      <input type="hidden" name="category_id" value={selectedId ?? ""} />
      <div className="flex flex-wrap items-center gap-1">
        <LocalRelationPicker items={choices} label={selected?.name ?? "انتخاب دسته‌بندی"}
          maxLength={255} disabled={creating} onSelect={(item) => choose(item.id)}
          onCreate={canCreate ? (query) => void create(query) : undefined} createLabel="تعریف دسته‌بندی" />
        {selectedId !== null && <Button type="button" variant="ghost" size="icon"
          aria-label="برداشتن دسته‌بندی از محصول" onClick={() => choose(null)}><X aria-hidden="true" /></Button>}
        {selected && canCreate && <Button type="button" size="sm" variant="ghost" onClick={beginEdit}>
          <Pencil aria-hidden="true" /> ویرایش دسته‌بندی انتخاب‌شده
        </Button>}
      </div>
      {creating && <p role="status" className="text-sm">در حال تعریف دسته‌بندی…</p>}
      {error && !editing && <p role="alert" className="text-sm text-destructive">{error}</p>}
      <Dialog open={editing} label="ویرایش دسته‌بندی" className="max-w-md"
        onClose={() => { setEditing(false); setError(null); }}>
        <div dir="rtl" className="space-y-4 p-6">
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
            <button type="button" disabled={updating} onClick={() => setEditing(false)}
              className="h-10 rounded-md border border-border px-4 text-sm">انصراف</button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
