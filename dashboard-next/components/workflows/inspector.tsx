"use client";
import { useState } from "react";
import { ScalarField } from "./scalar-field";
import { ActionBindingEditor } from "@/components/actions/binding-editor";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  ButtonsEditor,
  ChoicesEditor,
  ConditionEditor,
  Field,
  Select,
} from "./fields";
import { workflowRequest, errorText } from "@/lib/workflows/client";
import { nodePorts } from "@/lib/workflows/state";
import type {
  Catalog,
  Choice,
  ChoicePage,
  Condition,
  Config,
  Definition,
  DomainNode,
  FieldSpec,
  MediaChoice,
  Issue,
  Platform,
  Scalar,
  WorkflowButton,
} from "@/lib/workflows/types";
/** Media choices are paged inside the owning Store; no credential URLs enter config. */
function MediaPicker({
  field,
  value,
  onChange,
  storeId,
  nodeType,
}: {
  field: FieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
  storeId: string;
  nodeType: string;
}) {
  const [items, setItems] = useState<MediaChoice[]>([]),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0),
    [more, setMore] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const multiple = field.kind === "media_list",
    selected = multiple
      ? ((value as number[]) ?? [])
      : value
        ? [Number(value)]
        : [];
  const load = async (reset = false) => {
    setBusy(true);
    setError("");
    try {
      const kind =
        nodeType === "send_photo"
          ? "photo"
          : nodeType === "send_video"
            ? "video"
            : nodeType === "send_document"
              ? "document"
              : "";
      const data = await workflowRequest<ChoicePage<MediaChoice>>(
        `/media?store_id=${encodeURIComponent(storeId)}&page=${reset ? 1 : page + 1}&q=${encodeURIComponent(query)}${kind ? `&kind=${kind}` : ""}`,
      );
      setItems((current) => (reset ? data.items : [...current, ...data.items]));
      setPage(data.page);
      setMore(data.has_more);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Input
          aria-label="جستجوی رسانه"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="نام فایل"
        />
        <Button
          size="sm"
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => void load(true)}
        >
          جستجو
        </Button>
      </div>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selected.map((id) => (
            <Button
              key={id}
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                onChange(multiple ? selected.filter((v) => v !== id) : null)
              }
            >
              حذف #{id}
            </Button>
          ))}
        </div>
      )}
      <div className="max-h-44 space-y-1 overflow-y-auto">
        {items.map((m) => (
          <label
            key={m.id}
            className="flex items-start gap-2 rounded border p-2 text-xs"
          >
            <input
              type={multiple ? "checkbox" : "radio"}
              name={`${field.key}-media`}
              checked={selected.includes(m.id)}
              onChange={(e) =>
                onChange(
                  multiple
                    ? e.target.checked
                      ? [...selected, m.id].slice(0, 10)
                      : selected.filter((id) => id !== m.id)
                    : m.id,
                )
              }
            />
            <span className="min-w-0 break-words">
              {m.name ?? `#${m.id}`} · {m.kind}
              <span className="block text-muted-foreground">
                {m.product_name}
              </span>
            </span>
          </label>
        ))}
      </div>
      {page > 0 && items.length === 0 && (
        <p className="text-xs">رسانه‌ای در این فروشگاه پیدا نشد.</p>
      )}
      {more && (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void load()}
          disabled={busy}
        >
          {busy
            ? "در حال دریافت…"
            : page
              ? "رسانه‌های بیشتر"
              : "دریافت رسانه‌های فروشگاه"}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
function ConfigControl({
  field,
  config,
  onChange,
  definition,
  catalog,
  storeId,
  nodeType,
}: {
  field: FieldSpec;
  config: Config;
  onChange: (v: unknown) => void;
  definition: Definition;
  catalog: Catalog;
  storeId: string;
  nodeType: string;
}) {
  const value = config[field.key];
  if (field.kind === "json")
    return <ScalarField key={`${String(config.variable)}-${field.key}`} label={field.label} value={(value ?? null) as Scalar} onChange={onChange} variable={definition.variables.find(variable => variable.name === config.variable)} />;
  if (field.kind === "textarea")
    return (
      <Textarea
        aria-label={field.label}
        rows={4}
        value={String(value ?? "")}
        maxLength={Number(field.schema.maxLength ?? 4096)}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  if (field.kind === "boolean")
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          aria-label={field.label}
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        {field.label}
      </label>
    );
  if (field.kind === "select")
    return (
      <Select
        label={field.label}
        value={String(value ?? "")}
        options={field.options.map((v) => ({ value: v, label: v }))}
        onChange={onChange}
      />
    );
  if (field.kind === "variable")
    return (
      <Select
        label={field.label}
        value={String(value ?? "")}
        options={[
          { value: "", label: "انتخاب متغیر" },
          ...definition.variables.map((v) => ({
            value: v.name,
            label: `${v.label || v.name} · ${v.type}`,
          })),
        ]}
        onChange={onChange}
      />
    );
  if (field.kind === "node")
    return (
      <Select
        label={field.label}
        value={String(value ?? "")}
        options={[
          { value: "", label: "انتخاب مقصد" },
          ...definition.nodes.map((n) => ({
            value: n.id,
            label: n.label || n.id,
          })),
        ]}
        onChange={onChange}
      />
    );
  if (field.kind === "condition")
    return (
      <ConditionEditor
        value={value as Condition | null}
        onChange={onChange}
        variables={definition.variables}
      />
    );
  if (field.kind === "buttons")
    return (
      <ButtonsEditor
        value={value as WorkflowButton[]}
        onChange={onChange}
        definition={definition}
        catalog={catalog}
      />
    );
  if (field.kind === "choices")
    return (
      <ChoicesEditor
        value={value as Choice[]}
        onChange={onChange}
        variable={definition.variables.find((v) => v.name === config.variable)}
      />
    );
  if (["media", "media_list"].includes(field.kind))
    return (
      <MediaPicker
        field={field}
        value={value}
        onChange={onChange}
        storeId={storeId}
        nodeType={nodeType}
      />
    );
  if (field.kind === "number")
    return (
      <Input
        aria-label={field.label}
        type="number"
        dir="ltr"
        min={Number(field.schema.minimum ?? 0)}
        max={Number(field.schema.maximum ?? 86400)}
        value={Number(value ?? 0)}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    );
  return (
    <Input
      aria-label={field.label}
      value={String(value ?? "")}
      maxLength={Number(field.schema.maxLength ?? 4096)}
      onChange={(e) =>
        onChange(
          e.target.value === "" &&
            Array.isArray(field.schema.anyOf) &&
            (field.schema.anyOf as { type?: string }[]).some(
              (s) => s.type === "null",
            )
            ? null
            : e.target.value,
        )
      }
    />
  );
}
/** One catalog drives every node form; platform overrides remain partial values. */
export function Inspector({
  node,
  definition,
  catalog,
  storeId,
  onNode,
  onConnect,
  onDelete,
  issues,
  disabled,
}: {
  node: DomainNode;
  definition: Definition;
  catalog: Catalog;
  storeId: string;
  onNode: (node: DomainNode) => void;
  onConnect: (port: string, target: string) => void;
  onDelete: () => void;
  disabled: boolean;
  issues: Issue[];
}) {
  const [platform, setPlatform] = useState<"base" | Platform>("base");
  const spec = catalog.nodes.find((s) => s.type === node.type)!;
  const config =
    platform === "base"
      ? node.config
      : { ...node.config, ...node.platform_overrides[platform] };
  const fields =
    node.type === "action"
      ? []
      : platform === "base"
        ? spec.fields
        : spec.fields.filter(
            (f) =>
              f.overridable ??
              ["text", "textarea", "media", "media_list"].includes(f.kind),
          );
  const set = (key: string, value: unknown) =>
    onNode(
      platform === "base"
        ? { ...node, config: { ...node.config, [key]: value } }
        : {
            ...node,
            platform_overrides: {
              ...node.platform_overrides,
              [platform]: {
                ...node.platform_overrides[platform],
                [key]: value,
              },
            },
          },
    );
  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-5">
      <legend className="mb-3 font-semibold">{spec.label}</legend>
      {node.type === "action" && (
        <ActionBindingEditor
          config={node.config}
          definition={definition}
          actions={catalog.actions ?? []}
          onChange={(config) => onNode({ ...node, config })}
        />
      )}
      <Field label="عنوان گره">
        <Input
          aria-label="عنوان گره"
          value={node.label}
          maxLength={120}
          onChange={(e) => onNode({ ...node, label: e.target.value })}
        />
      </Field>
      <code className="block break-all text-xs text-muted-foreground" dir="ltr">
        {node.id} · {node.type}
      </code>
      <Select
        label="نسخهٔ تنظیمات گره"
        value={platform}
        options={[
          { value: "base", label: "تنظیم مشترک" },
          ...definition.target_platforms.map((p) => ({
            value: p,
            label: p === "telegram" ? "Telegram override" : "Bale override",
          })),
        ]}
        onChange={(v) => setPlatform(v as typeof platform)}
      />
      {platform !== "base" && (
        <p className="text-xs leading-6 text-muted-foreground">
          فقط متن و رسانهٔ متفاوت را ثبت کنید. مسیرها و متغیرها مشترک می‌مانند.
        </p>
      )}
      {fields
        .filter((f) =>
          Object.entries(f.show_if).every(([k, v]) => config[k] === v),
        )
        .map((f) => (
          <Field
            key={f.key}
            label={`${f.label}${f.required ? " *" : ""}`}
            hint={f.help || undefined}
          >
            <ConfigControl
              field={f}
              config={config}
              onChange={(v) => set(f.key, v)}
              definition={definition}
              catalog={catalog}
              storeId={storeId}
              nodeType={node.type}
            />
            {issues
              .filter(
                (i) =>
                  i.field === f.key &&
                  (platform === "base" || i.platform === platform),
              )
              .map((issue, i) => (
                <p
                  key={i}
                  role="alert"
                  className="text-xs leading-6 text-destructive"
                >
                  {issue.message}
                </p>
              ))}
            {platform !== "base" &&
              Object.hasOwn(node.platform_overrides[platform] ?? {}, f.key) && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const override = { ...node.platform_overrides[platform] };
                    delete override[f.key];
                    onNode({
                      ...node,
                      platform_overrides: {
                        ...node.platform_overrides,
                        [platform]: override,
                      },
                    });
                  }}
                >
                  استفاده از مقدار مشترک
                </Button>
              )}
          </Field>
        ))}
      {platform === "base" && (
        <>
          <Field
            label="حداکثر بازدید در چرخه"
            hint="برای چرخه، هر گره باید حد بازدید و مسیر خروج داشته باشد؛ خالی یعنی بدون تکرار."
          >
            <Input
              aria-label="حداکثر بازدید در چرخه"
              type="number"
              min={1}
              max={25}
              value={node.max_visits ?? ""}
              onChange={(e) =>
                onNode({
                  ...node,
                  max_visits: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
          </Field>
          <div className="space-y-3 border-t pt-4">
            <h3 className="text-sm font-semibold">اتصال خروجی‌ها</h3>
            {nodePorts(node, spec).map((port) => (
              <Field key={port} label={port}>
                <Select
                  label={`مقصد ${port}`}
                  value={
                    definition.edges.find(
                      (e) => e.source === node.id && e.port === port,
                    )?.target ??
                    (node.type === "show_buttons"
                      ? (node.config.buttons as WorkflowButton[]).find(
                          (b) => b.key === port,
                        )?.target
                      : node.type === "go_to_step"
                        ? String(node.config.target ?? "")
                        : "") ??
                    ""
                  }
                  options={[
                    { value: "", label: "بدون اتصال" },
                    ...definition.nodes.map((n) => ({
                      value: n.id,
                      label: n.label || n.id,
                    })),
                  ]}
                  onChange={(target) => onConnect(port, target)}
                />
              </Field>
            ))}
            <Button
              type="button"
              size="sm"
              variant="destructive"
              onClick={onDelete}
            >
              حذف گره
            </Button>
          </div>
        </>
      )}
      {spec.action_contract.simulation_only && (
        <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs leading-6">
          این Action در Preview فقط نتیجهٔ نمونه می‌دهد.
          {!spec.action_contract.available &&
            " قرارداد اجرای این قابلیت هنوز آماده نیست."}
        </p>
      )}
    </fieldset>
  );
}
