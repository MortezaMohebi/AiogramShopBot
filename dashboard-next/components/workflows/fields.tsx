"use client";
import { useId, useState, type ReactNode } from "react";
import { Plus, Trash2, ChevronUp, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  Catalog,
  Choice,
  Condition,
  Definition,
  Scalar,
  Variable,
  VariableType,
  WorkflowButton,
} from "@/lib/workflows/types";
export const selectClass =
  "h-10 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring disabled:opacity-60";
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="min-w-0 space-y-2" role="group" aria-labelledby={id}>
      <div id={id} className="text-xs font-semibold">
        {label}
      </div>
      {children}
      {hint && (
        <p className="text-xs leading-6 text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}
export function Select({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <select
      aria-label={label}
      className={selectClass}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
const variableTypes: VariableType[] = [
  "string",
  "integer",
  "decimal",
  "boolean",
  "date",
  "datetime",
  "enum",
  "product_ref",
  "category_ref",
  "order_ref",
  "customer_ref",
];
/** Typed constants never accept arbitrary JSON, scripts or customer objects. */
export function ValueField({
  label,
  type = "string",
  value,
  onChange,
  choices = [],
}: {
  label: string;
  type?: VariableType;
  value: Scalar;
  onChange: (v: Scalar) => void;
  choices?: string[];
}) {
  if (type === "boolean")
    return (
      <Select
        label={label}
        value={value === null ? "" : String(value)}
        onChange={(v) => onChange(v === "" ? null : v === "true")}
        options={[
          { value: "", label: "بدون مقدار" },
          { value: "true", label: "درست" },
          { value: "false", label: "نادرست" },
        ]}
      />
    );
  if (type === "enum")
    return (
      <Select
        label={label}
        value={String(value ?? "")}
        onChange={(v) => onChange(v || null)}
        options={[
          { value: "", label: "بدون مقدار" },
          ...choices.map((v) => ({ value: v, label: v })),
        ]}
      />
    );
  if (type.endsWith("_ref"))
    return (
      <Input
        aria-label={label}
        dir="ltr"
        inputMode="numeric"
        type="number"
        min={1}
        max={9007199254740991}
        value={value && typeof value === "object" ? value.id : ""}
        placeholder="شناسهٔ نمونه"
        onChange={(e) =>
          onChange(
            e.target.value
              ? {
                  kind: type.slice(0, -4) as "product" | "category" | "order" | "customer",
                  id: Number(e.target.value),
                }
              : null,
          )
        }
      />
    );
  return (
    <Input
      aria-label={label}
      dir={type === "string" ? undefined : "ltr"}
      type={type === "date" ? "date" : type === "integer" ? "number" : "text"}
      inputMode={type === "decimal" ? "decimal" : undefined}
      value={typeof value === "object" ? "" : String(value ?? "")}
      placeholder={
        type === "datetime" ? "2026-11-05T12:00:00+03:30" : undefined
      }
      onChange={(e) =>
        onChange(
          e.target.value === ""
            ? null
            : type === "integer"
              ? Number(e.target.value)
              : e.target.value,
        )
      }
    />
  );
}
const publicVariables = [
  "context.platform",
  "context.customer_name",
  "context.store_name",
  "context.bot_name",
];
export function ConditionEditor({
  value,
  onChange,
  variables,
  depth = 0,
}: {
  value: Condition | null;
  onChange: (v: Condition | null) => void;
  variables: Variable[];
  depth?: number;
}) {
  const rule = (): Condition => ({
    kind: "rule",
    variable: variables[0]?.name ?? "context.platform",
    operator: "eq",
    value: "telegram",
  });
  if (!value)
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange(rule())}
      >
        افزودن شرط
      </Button>
    );
  const variable =
    value.kind === "rule"
      ? variables.find((v) => v.name === value.variable)
      : undefined;
  return (
    <div className="min-w-0 space-y-3 rounded-lg border border-border bg-muted/20 p-3">
      <div className="flex gap-2">
        <Select
          label="نوع شرط"
          value={value.kind}
          options={[
            { value: "rule", label: "مقایسه" },
            { value: "all", label: "همهٔ شرط‌ها (AND)" },
            { value: "any", label: "یکی از شرط‌ها (OR)" },
          ]}
          onChange={(kind) =>
            onChange(
              kind === "rule"
                ? rule()
                : { kind: kind as "all" | "any", terms: [rule()] },
            )
          }
        />
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label="حذف شرط"
          onClick={() => onChange(null)}
        >
          <Trash2 />
        </Button>
      </div>
      {value.kind === "rule" ? (
        <>
          <Select
            label="متغیر شرط"
            value={value.variable}
            options={[
              ...variables.map((v) => ({
                value: v.name,
                label: v.label || v.name,
              })),
              ...publicVariables.map((v) => ({ value: v, label: v })),
            ]}
            onChange={(v) => onChange({ ...value, variable: v, value: null })}
          />
          <Select
            label="عملگر شرط"
            value={value.operator}
            options={[
              { value: "eq", label: "برابر" },
              { value: "neq", label: "نابرابر" },
              { value: "gt", label: "بزرگ‌تر" },
              { value: "lt", label: "کوچک‌تر" },
              { value: "contains", label: "شامل" },
              { value: "exists", label: "مقدار دارد" },
              { value: "is_empty", label: "خالی است" },
            ]}
            onChange={(v) =>
              onChange({
                ...value,
                operator: v as typeof value.operator,
                value: null,
              })
            }
          />
          {!["exists", "is_empty"].includes(value.operator) && (
            <ValueField
              label="مقدار مقایسه"
              type={variable?.type ?? "string"}
              choices={variable?.choices}
              value={value.value}
              onChange={(v) => onChange({ ...value, value: v })}
            />
          )}
        </>
      ) : (
        <>
          {value.terms.map((term, i) => (
            <ConditionEditor
              key={i}
              value={term}
              variables={variables}
              depth={depth + 1}
              onChange={(v) => {
                const terms = value.terms.flatMap((t, j) =>
                  j === i ? (v ? [v] : []) : [t],
                );
                onChange(terms.length ? { ...value, terms } : null);
              }}
            />
          ))}
          {depth < 5 && value.terms.length < 20 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                onChange({ ...value, terms: [...value.terms, rule()] })
              }
            >
              افزودن مقایسه
            </Button>
          )}
        </>
      )}
    </div>
  );
}
export function ChoicesEditor({
  value,
  onChange,
  variable,
}: {
  value: Choice[];
  onChange: (v: Choice[]) => void;
  variable?: Variable;
}) {
  return (
    <div className="space-y-3">
      {value.map((c, i) => (
        <div key={c.key} className="space-y-2 rounded-lg border p-3">
          <div className="flex gap-2">
            <Input
              aria-label={`عنوان گزینه ${i + 1}`}
              value={c.label}
              onChange={(e) =>
                onChange(
                  value.map((v, j) =>
                    j === i ? { ...v, label: e.target.value } : v,
                  ),
                )
              }
            />
            <Button
              type="button"
              size="icon"
              variant="ghost"
              aria-label={`حذف گزینه ${i + 1}`}
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              <Trash2 />
            </Button>
          </div>
          <ValueField
            label={`مقدار گزینه ${i + 1}`}
            value={c.value}
            type={variable?.type ?? "string"}
            choices={variable?.choices}
            onChange={(v) =>
              onChange(value.map((c, j) => (j === i ? { ...c, value: v } : c)))
            }
          />
          <code className="break-all text-xs" dir="ltr">
            {c.key}
          </code>
        </div>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={value.length >= 100}
        onClick={() =>
          onChange([
            ...value,
            {
              key: `choice_${crypto.randomUUID().replaceAll("-", "").slice(0, 10)}`,
              label: "گزینهٔ جدید",
              value:
                variable?.type === "integer" ? value.length + 1 : "new_value",
            },
          ])
        }
      >
        <Plus />
        گزینه
      </Button>
    </div>
  );
}
/** Schema-backed buttons expose navigation and visibility; no callback business data. */
export function ButtonsEditor({
  value,
  onChange,
  definition,
  catalog,
}: {
  value: WorkflowButton[];
  onChange: (v: WorkflowButton[]) => void;
  definition: Definition;
  catalog: Catalog;
}) {
  const update = (i: number, change: Partial<WorkflowButton>) =>
    onChange(value.map((b, j) => (j === i ? { ...b, ...change } : b)));
  const move = (i: number, delta: number) => {
    const next = [...value];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    onChange(next);
  };
  return (
    <div className="space-y-3">
      {value.map((b, i) => (
        <details
          key={b.key}
          className="rounded-lg border bg-background p-3"
          open
        >
          <summary className="cursor-pointer text-xs font-semibold">
            {i + 1}. {b.label}
          </summary>
          <div className="mt-3 space-y-3">
            <Input
              aria-label={`متن دکمه ${i + 1}`}
              value={b.label}
              maxLength={80}
              onChange={(e) => update(i, { label: e.target.value })}
            />
            <Select
              label={`نوع دکمه ${i + 1}`}
              value={b.type}
              options={[
                { value: "callback", label: "رفتن به مرحله" },
                { value: "url", label: "لینک HTTPS" },
                { value: "action", label: "Action آماده" },
                { value: "request_contact", label: "درخواست Contact" },
                { value: "back", label: "بازگشت" },
                { value: "cancel", label: "لغو" },
                { value: "main_menu", label: "منوی اصلی" },
              ]}
              onChange={(type) =>
                update(i, {
                  type: type as WorkflowButton["type"],
                  target: "",
                  url: "",
                  action: "",
                })
              }
            />
            {["callback", "action"].includes(b.type) && (
              <Select
                label={`مقصد دکمه ${i + 1}`}
                value={b.target}
                options={[
                  { value: "", label: "مقصد انتخاب نشده" },
                  ...definition.nodes.map((n) => ({
                    value: n.id,
                    label: n.label || n.id,
                  })),
                ]}
                onChange={(target) => update(i, { target })}
              />
            )}{" "}
            {b.type === "url" && (
              <Input
                aria-label={`لینک دکمه ${i + 1}`}
                type="url"
                dir="ltr"
                placeholder="https://example.com"
                value={b.url}
                onChange={(e) => update(i, { url: e.target.value })}
              />
            )}{" "}
            {b.type === "action" && (
              <Select
                label={`Action دکمه ${i + 1}`}
                value={b.action}
                options={[
                  { value: "", label: "انتخاب Action" },
                  ...catalog.nodes
                    .filter((n) => n.action_contract.simulation_only)
                    .map((n) => ({ value: n.type, label: n.label })),
                ]}
                onChange={(action) => update(i, { action })}
              />
            )}
            <Field label="ردیف صفحه‌کلید">
              <Input
                aria-label={`ردیف دکمه ${i + 1}`}
                type="number"
                min={0}
                max={15}
                value={b.row}
                onChange={(e) =>
                  update(i, {
                    row: Math.max(0, Math.min(15, Number(e.target.value))),
                  })
                }
              />
            </Field>
            <div className="flex flex-wrap gap-4">
              {(["telegram", "bale"] as const).map((p) => (
                <label key={p} className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={b.platforms.includes(p)}
                    onChange={(e) =>
                      update(i, {
                        platforms: e.target.checked
                          ? [...b.platforms, p]
                          : b.platforms.filter((v) => v !== p),
                      })
                    }
                  />
                  {p === "telegram" ? "Telegram" : "Bale"}
                </label>
              ))}
            </div>
            <Field label="شرط نمایش">
              <ConditionEditor
                value={b.visible_when}
                onChange={(v) => update(i, { visible_when: v })}
                variables={definition.variables}
              />
            </Field>
            <div className="flex gap-1">
              <Button
                type="button"
                size="icon"
                variant="outline"
                aria-label="بالابردن دکمه"
                disabled={i === 0}
                onClick={() => move(i, -1)}
              >
                <ChevronUp />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="outline"
                aria-label="پایین‌بردن دکمه"
                disabled={i === value.length - 1}
                onClick={() => move(i, 1)}
              >
                <ChevronDown />
              </Button>
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={`حذف دکمه ${i + 1}`}
                onClick={() => onChange(value.filter((_, j) => j !== i))}
              >
                <Trash2 />
              </Button>
            </div>
            <p className="break-all text-xs text-muted-foreground" dir="ltr">
              {b.key}
            </p>
          </div>
        </details>
      ))}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={value.length >= 60}
        onClick={() =>
          onChange([
            ...value,
            {
              key: `button_${crypto.randomUUID().replaceAll("-", "").slice(0, 10)}`,
              label: "ادامه",
              type: "callback",
              target: "",
              action: "",
              url: "",
              row: Math.min(15, value.length),
              visible_when: null,
              platforms: ["telegram", "bale"],
            },
          ])
        }
      >
        <Plus />
        افزودن دکمه
      </Button>
      <p className="text-xs leading-6 text-muted-foreground">
        مقصد به شناسهٔ گره متصل است. Callback واقعی هنگام اجرای نسخهٔ منتشرشده، با وضعیت سرور اعتبارسنجی
        می‌شود.
      </p>
    </div>
  );
}
/** Keep the raw multiline value while normalizing portable enum choices. */
function EnumOptions({
  value,
  onChange,
  label,
}: {
  value: string[];
  onChange: (v: string[]) => void;
  label: string;
}) {
  const normalize = (text: string) => [
    ...new Set(text.split("\n").filter(Boolean)),
  ];
  const [raw, setRaw] = useState(value.join("\n"));
  if (normalize(raw).join("\n") !== normalize(value.join("\n")).join("\n"))
    setRaw(value.join("\n"));
  return (
    <Textarea
      aria-label={label}
      dir="ltr"
      value={raw}
      placeholder="هر مقدار در یک خط"
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(normalize(e.target.value));
      }}
    />
  );
}
export function VariablesEditor({
  value,
  onChange,
}: {
  value: Variable[];
  onChange: (v: Variable[]) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const update = (i: number, change: Partial<Variable>) =>
    onChange(value.map((v, j) => (j === i ? { ...v, ...change } : v)));
  return (
    <div className="space-y-3">
      {value.map((v, i) => (
        <details
          key={i}
          className="rounded-lg border p-3"
          open={open === String(i)}
          onToggle={(e) => {
            if (e.currentTarget.open) setOpen(String(i));
          }}
        >
          <summary className="cursor-pointer break-all text-xs">
            <bdi>{v.name}</bdi> · {v.type}
          </summary>
          <div className="mt-3 space-y-3">
            <Input
              aria-label={`نام متغیر ${i + 1}`}
              dir="ltr"
              pattern="[a-z][a-z0-9_]{0,47}"
              value={v.name}
              maxLength={48}
              onChange={(e) => update(i, { name: e.target.value })}
            />
            <Input
              aria-label={`عنوان متغیر ${i + 1}`}
              value={v.label}
              onChange={(e) => update(i, { label: e.target.value })}
            />
            <Select
              label={`نوع متغیر ${i + 1}`}
              value={v.type}
              options={variableTypes.map((t) => ({ value: t, label: t }))}
              onChange={(type) =>
                update(i, {
                  type: type as VariableType,
                  default: null,
                  choices: [],
                })
              }
            />
            <Select
              label={`دامنه متغیر ${i + 1}`}
              value={v.scope}
              options={[
                { value: "workflow", label: "Workflow" },
                { value: "input", label: "Input" },
              ]}
              onChange={(scope) =>
                update(i, { scope: scope as Variable["scope"] })
              }
            />
            {v.type === "enum" && (
              <EnumOptions
                label={`مقادیر enum ${i + 1}`}
                value={v.choices}
                onChange={(choices) => update(i, { choices })}
              />
            )}
            <ValueField
              label={`پیش‌فرض متغیر ${i + 1}`}
              type={v.type}
              choices={v.choices}
              value={v.default}
              onChange={(value) => update(i, { default: value })}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange(value.filter((_, j) => j !== i))}
            >
              <Trash2 />
              حذف متغیر
            </Button>
          </div>
        </details>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={value.length >= 100}
        onClick={() => {
          onChange([
            ...value,
            {
              name: `value_${crypto.randomUUID().replaceAll("-", "").slice(0, 8)}`,
              type: "string",
              scope: "workflow",
              label: "",
              choices: [],
              default: null,
            },
          ]);
          setOpen(String(value.length));
        }}
      >
        <Plus />
        متغیر
      </Button>
    </div>
  );
}
