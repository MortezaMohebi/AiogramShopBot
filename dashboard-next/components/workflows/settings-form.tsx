"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, Select, VariablesEditor } from "./fields";
import { errorText, workflowRequest } from "@/lib/workflows/client";
import type {
  BotChoice,
  ChoicePage,
  DraftDocument,
  EntryPoint,
  Platform,
} from "@/lib/workflows/types";
export function BotPicker({
  storeId,
  selected,
  onChange,
  platforms,
}: {
  storeId: string;
  selected: string[];
  onChange: (ids: string[]) => void;
  platforms: Platform[];
}) {
  const [items, setItems] = useState<BotChoice[]>([]),
    [page, setPage] = useState(0),
    [more, setMore] = useState(true),
    [query, setQuery] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const load = async (reset = false) => {
    setBusy(true);
    setError("");
    try {
      const response = await workflowRequest<ChoicePage<BotChoice>>(
        `/bots?store_id=${encodeURIComponent(storeId)}&page=${reset ? 1 : page + 1}&q=${encodeURIComponent(query)}`,
      );
      setItems((current) =>
        reset ? response.items : [...current, ...response.items],
      );
      setPage(response.page);
      setMore(response.has_more);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <Input
          aria-label="جستجوی ربات"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void load(true)}
          disabled={busy}
        >
          جستجو
        </Button>
      </div>
      <p className="text-xs">{selected.length} ربات انتخاب شده</p>
      {selected
        .filter((id) => !items.some((b) => b.id === id))
        .map((id) => (
          <div key={id} className="flex items-center gap-2 text-xs">
            <bdi className="min-w-0 break-all">{id}</bdi>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onChange(selected.filter((v) => v !== id))}
            >
              حذف انتخاب
            </Button>
          </div>
        ))}
      <div className="max-h-64 space-y-2 overflow-y-auto">
        {items.map((b) => (
          <label
            key={b.id}
            className="flex items-center gap-3 rounded-lg border p-3 text-sm"
          >
            <input
              type="checkbox"
              checked={selected.includes(b.id)}
              disabled={!platforms.includes(b.platform)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...selected, b.id]
                    : selected.filter((id) => id !== b.id),
                )
              }
            />
            <span>
              {b.name}{" "}
              <span className="text-xs text-muted-foreground">
                {b.platform} · {b.status}
              </span>
            </span>
          </label>
        ))}
      </div>
      {more && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => void load()}
        >
          {busy
            ? "در حال دریافت…"
            : page
              ? "ربات‌های بیشتر"
              : "دریافت ربات‌های فروشگاه"}
        </Button>
      )}
      {page > 0 && items.length === 0 && (
        <p className="text-sm text-muted-foreground">
          ربات واجد شرایطی در این فروشگاه پیدا نشد.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
export function WorkflowSettings({
  document,
  onChange,
  storeId,
  disabled,
}: {
  document: DraftDocument;
  onChange: (d: DraftDocument) => void;
  storeId: string;
  disabled: boolean;
}) {
  const d = document.definition;
  const update = (change: Partial<typeof d>) =>
    onChange({ ...document, definition: { ...d, ...change } });
  const entry = (i: number, change: Partial<EntryPoint>) =>
    update({
      entry_points: d.entry_points.map((e, j) =>
        j === i ? { ...e, ...change } : e,
      ),
    });
  return (
    <fieldset disabled={disabled} className="grid min-w-0 gap-6 lg:grid-cols-2">
      <legend className="sr-only">تنظیمات فرایند</legend>
      <div className="min-w-0 space-y-6 rounded-xl border bg-card p-5">
        <h2 className="font-semibold">مشخصات فرایند و ربات‌ها</h2>
        <p className="text-xs text-muted-foreground">
          شناسهٔ فروشگاه: <bdi className="break-all" dir="ltr">{storeId}</bdi>
        </p>
        <Field label="نام فرایند">
          <Input
            aria-label="نام فرایند"
            value={document.name}
            maxLength={160}
            onChange={(e) => onChange({ ...document, name: e.target.value })}
          />
        </Field>
        <Field label="توضیحات">
          <Textarea
            aria-label="توضیحات فرایند"
            value={document.description}
            maxLength={4000}
            onChange={(e) =>
              onChange({ ...document, description: e.target.value })
            }
          />
        </Field>
        <Field label="پیام‌رسان‌ها">
          <div className="flex gap-5">
            {(["telegram", "bale"] as const).map((p) => (
              <label key={p} className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={d.target_platforms.includes(p)}
                  onChange={(e) =>
                    update({
                      target_platforms: e.target.checked
                        ? [...d.target_platforms, p]
                        : d.target_platforms.filter((v) => v !== p),
                    })
                  }
                />
                {p === "telegram" ? "تلگرام" : "بله"}
              </label>
            ))}
          </div>
        </Field>
        <Field label="تخصیص ربات">
          <Select
            label="روش تخصیص ربات"
            value={d.assignment.mode}
            options={[
              {
                value: "all_eligible",
                label: "همهٔ ربات‌های واجد شرایط همین فروشگاه",
              },
              { value: "selected", label: "ربات‌های انتخاب‌شدهٔ همین فروشگاه" },
            ]}
            onChange={(v) =>
              update({
                assignment: {
                  mode: v as "selected" | "all_eligible",
                  bot_ids: [],
                },
              })
            }
          />
        </Field>
        {d.assignment.mode === "selected" ? (
          <BotPicker
            storeId={storeId}
            selected={d.assignment.bot_ids}
            platforms={d.target_platforms}
            onChange={(bot_ids) =>
              update({ assignment: { ...d.assignment, bot_ids } })
            }
          />
        ) : (
          <p className="text-xs leading-6 text-muted-foreground">
            ربات غیرفعال و پلتفرم نامرتبط واجد شرایط نیست. این تخصیص تغییری در
            منوی فعال مشتری ایجاد نمی‌کند.
          </p>
        )}
        <div className="space-y-3 border-t pt-5">
          <h3 className="text-sm font-semibold">ورودی‌ها</h3>
          {d.entry_points.map((e, i) => (
            <div key={i} className="space-y-2 rounded-lg border p-3">
              <Field label="کلید ورودی">
                <Input
                  dir="ltr"
                  aria-label={`کلید ورودی ${i + 1}`}
                  value={e.key}
                  maxLength={64}
                  onChange={(ev) => entry(i, { key: ev.target.value })}
                />
              </Field>
              <Field label="نوع ورودی">
                <Select
                  label={`نوع ورودی ${i + 1}`}
                  value={e.kind}
                  options={[
                    { value: "start", label: "شروع" },
                    { value: "command", label: "دستور" },
                    { value: "menu", label: "منو" },
                    { value: "internal", label: "داخلی" },
                  ]}
                  onChange={(kind) =>
                    entry(i, { kind: kind as EntryPoint["kind"] })
                  }
                />
              </Field>
              <Field label="گره ورودی">
                <Select
                  label={`گره ورودی ${i + 1}`}
                  value={e.node_id}
                  options={d.nodes.map((n) => ({
                    value: n.id,
                    label: n.label || n.id,
                  }))}
                  onChange={(node_id) => entry(i, { node_id })}
                />
              </Field>
              {e.kind === "command" && (
                <Field label="دستور">
                  <Input
                    dir="ltr"
                    aria-label={`دستور ورودی ${i + 1}`}
                    value={e.command}
                    placeholder="request_return"
                    onChange={(ev) => entry(i, { command: ev.target.value })}
                  />
                </Field>
              )}
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() =>
                  update({
                    entry_points: d.entry_points.filter((_, j) => j !== i),
                  })
                }
              >
                حذف ورودی
              </Button>
            </div>
          ))}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              update({
                entry_points: [
                  ...d.entry_points,
                  {
                    key: `entry_${crypto.randomUUID().slice(0, 8)}`,
                    kind: "menu",
                    node_id:
                      d.nodes.find((n) => n.type === "start")?.id ??
                      d.nodes[0]?.id ??
                      "",
                    command: "",
                  },
                ],
              })
            }
          >
            افزودن ورودی
          </Button>
        </div>
      </div>
      <div className="min-w-0 space-y-6 rounded-xl border bg-card p-5">
        <h2 className="font-semibold">متغیرها و سیاست‌ها</h2>
        <VariablesEditor
          value={d.variables}
          onChange={(variables) => update({ variables })}
        />
        <Field label="حداکثر مراحل هر اجرا">
          <Input
            aria-label="حداکثر مراحل هر اجرا"
            type="number"
            min={1}
            max={500}
            value={d.error_policy.max_steps}
            onChange={(e) =>
              update({
                error_policy: {
                  ...d.error_policy,
                  max_steps: Number(e.target.value),
                },
              })
            }
          />
        </Field>
        <Field label="رفتار خطا">
          <Select
            label="رفتار خطا"
            value={d.error_policy.on_error}
            options={[
              { value: "stop", label: "توقف" },
              { value: "cancel", label: "لغو" },
            ]}
            onChange={(v) =>
              update({
                error_policy: {
                  ...d.error_policy,
                  on_error: v as "stop" | "cancel",
                },
              })
            }
          />
        </Field>
        <Field label="پیام خطا">
          <Textarea
            aria-label="پیام خطا"
            value={d.error_policy.message}
            onChange={(e) =>
              update({
                error_policy: { ...d.error_policy, message: e.target.value },
              })
            }
          />
        </Field>
        <Field label="مهلت پاسخ (ثانیه)">
          <Input
            aria-label="مهلت پاسخ (ثانیه)"
            type="number"
            min={1}
            max={86400}
            value={d.timeout_policy.seconds}
            onChange={(e) =>
              update({
                timeout_policy: {
                  ...d.timeout_policy,
                  seconds: Number(e.target.value),
                },
              })
            }
          />
        </Field>
        <Select
          label="پس از پایان مهلت"
          value={d.timeout_policy.outcome}
          options={[
            { value: "cancel", label: "لغو" },
            { value: "end", label: "پایان" },
          ]}
          onChange={(outcome) =>
            update({
              timeout_policy: {
                ...d.timeout_policy,
                outcome: outcome as "cancel" | "end",
              },
            })
          }
        />
        <div className="rounded-lg border bg-muted/30 p-4 text-sm leading-7">
          ذخیرهٔ تنظیمات، نسخهٔ فعال ربات را تغییر نمی‌دهد. برای اعمال تغییرات روی ربات، نسخهٔ ذخیره‌شده را در بخش «انتشار و اجرا» منتشر کنید.
        </div>
      </div>
    </fieldset>
  );
}
