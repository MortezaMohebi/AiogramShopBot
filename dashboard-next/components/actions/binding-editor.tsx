"use client";
import Link from "next/link";
import { Field, Select, ValueField } from "@/components/workflows/fields";
import {
  mappingVariables,
  primitiveSchema,
  sideEffectLabels,
} from "@/lib/actions/state";
import type {
  ActionConfig,
  ActionDescriptor,
  InputSource,
} from "@/lib/actions/types";
import type {
  Config,
  Definition,
  Scalar,
  VariableType,
} from "@/lib/workflows/types";

const publicContext = [
  "context.platform",
  "context.customer_name",
  "context.store_name",
  "context.bot_name",
];
/** The inspector edits only typed sources/targets, never scripts or arbitrary object paths. */
export function ActionBindingEditor({
  config,
  definition,
  actions,
  onChange,
}: {
  config: Config;
  definition: Definition;
  actions: ActionDescriptor[];
  onChange: (config: Config) => void;
}) {
  const value = config as ActionConfig;
  const selected = actions.find(
    (item) =>
      item.key === value.action_key && item.version === value.action_version,
  );
  const input = value.input_mapping ?? {},
    output = value.output_mapping ?? {};
  const choose = (key: string, version?: string) => {
    const action = actions.find(
      (item) => item.key === key && (!version || item.version === version),
    );
    onChange({
      action_key: key,
      action_version: action?.version ?? "1.0.0",
      input_mapping: {},
      output_mapping: {},
    });
  };
  const setInput = (key: string, source: InputSource | null) => {
    const mapping = { ...input };
    if (source) mapping[key] = source;
    else delete mapping[key];
    onChange({ ...value, input_mapping: mapping });
  };
  const setOutput = (key: string, target: string) => {
    const mapping = { ...output };
    if (target) mapping[key] = target;
    else delete mapping[key];
    onChange({ ...value, output_mapping: mapping });
  };
  const keys = [...new Set(actions.map((item) => item.key))];
  return (
    <div className="space-y-5">
      <Field label="Action">
        <Select
          label="Action"
          value={value.action_key ?? ""}
          onChange={(key) => choose(key)}
          options={[
            { value: "", label: "انتخاب Action" },
            ...keys.map((key) => ({
              value: key,
              label: `${actions.find((item) => item.key === key)?.name} · ${key}`,
            })),
          ]}
        />
      </Field>
      <Field label="نسخهٔ Action">
        <Select
          label="نسخهٔ Action"
          value={value.action_version ?? "1.0.0"}
          onChange={(version) => choose(value.action_key, version)}
          options={actions
            .filter((item) => item.key === value.action_key)
            .map((item) => ({
              value: item.version,
              label: `${item.version}${item.deprecated ? " · منسوخ" : ""}`,
            }))}
        />
      </Field>
      <Link href="/studio/actions" className="text-xs text-primary underline">
        مشاهدهٔ عملیات آماده و سیاست‌ها
      </Link>
      {selected ? (
        <>
          <div className="space-y-2 rounded border p-3 text-xs leading-6 text-muted-foreground">
            <p>
              {sideEffectLabels[selected.side_effect]} · Idempotency:{" "}
              <bdi>{selected.idempotency}</bdi>
            </p>
            <p>
              شرایط تأیید: <bdi>{selected.confirmation}</bdi>
            </p>
            {!selected.service_available && (
              <p>
                اجرای واقعی این عملیات در دسترس نیست. شبیه‌ساز فقط خروجی آزمایشی
                نشان می‌دهد.
              </p>
            )}
            {selected.deprecated && (
              <p>این نسخه منسوخ شده است؛ جایگزین را در فهرست عملیات بررسی کنید.</p>
            )}
          </div>
          <div className="space-y-4">
            <h3 className="text-sm font-semibold">ورودی‌های Action</h3>
            {Object.entries(selected.input_schema.properties ?? {}).map(
              ([name, raw]) => {
                const schema = primitiveSchema(raw),
                  source = input[name];
                const variables = mappingVariables(
                  raw,
                  name,
                  definition.variables,
                );
                const constantType: VariableType = schema.enum
                  ? "enum"
                  : schema.type === "integer"
                    ? "integer"
                    : schema.type === "boolean"
                      ? "boolean"
                      : "string";
                return (
                  <div key={name} className="space-y-2 rounded border p-3">
                    <Field
                      label={`${name}${selected.input_schema.required?.includes(name) ? " *" : ""}`}
                    >
                      <Select
                        label={`منبع ${name}`}
                        value={source?.kind ?? ""}
                        onChange={(kind) =>
                          setInput(
                            name,
                            kind
                              ? {
                                  kind: kind as InputSource["kind"],
                                  name: "",
                                  value: null,
                                }
                              : null,
                          )
                        }
                        options={[
                          {
                            value: "",
                            label: "بدون اتصال؛ استفاده از پیش‌فرض",
                          },
                          { value: "constant", label: "مقدار ثابت" },
                          { value: "variable", label: "متغیر تعریف‌شده" },
                          ...(schema.type === "string"
                            ? [{ value: "context", label: "Context مجاز" }]
                            : []),
                        ]}
                      />
                    </Field>
                    {source?.kind === "constant" && (
                      <ValueField
                        label={`مقدار ثابت ${name}`}
                        type={constantType}
                        value={source.value as Scalar}
                        choices={schema.enum?.map(String) ?? []}
                        onChange={(constant) =>
                          setInput(name, { ...source, value: constant })
                        }
                      />
                    )}
                    {source?.kind === "variable" && (
                      <Select
                        label={`متغیر ${name}`}
                        value={source.name}
                        onChange={(variable) =>
                          setInput(name, { ...source, name: variable })
                        }
                        options={[
                          { value: "", label: "انتخاب متغیر سازگار" },
                          ...variables.map((variable) => ({
                            value: variable.name,
                            label: `${variable.label || variable.name} · ${variable.type}`,
                          })),
                        ]}
                      />
                    )}
                    {source?.kind === "context" && (
                      <Select
                        label={`Context ${name}`}
                        value={source.name}
                        onChange={(context) =>
                          setInput(name, { ...source, name: context })
                        }
                        options={[
                          { value: "", label: "انتخاب کلید Context" },
                          ...publicContext.map((context) => ({
                            value: context,
                            label: context,
                          })),
                        ]}
                      />
                    )}
                    {selected.sensitive_inputs.includes(name) && (
                      <p className="text-[11px] text-muted-foreground">
                        ورودی خصوصی؛ محتوای آن در خلاصهٔ رسید و گزارش‌ها نمایش داده
                        نمی‌شود.
                      </p>
                    )}
                  </div>
                );
              },
            )}
            {Object.keys(selected.input_schema.properties ?? {}).length ===
              0 && (
              <p className="text-xs text-muted-foreground">
                این Action ورودی قابل تنظیم ندارد.
              </p>
            )}
          </div>
          <div className="space-y-3">
            <h3 className="text-sm font-semibold">خروجی به متغیر</h3>
            {Object.entries(selected.output_schema.properties ?? {}).map(
              ([name, schema]) => {
                const variables = mappingVariables(
                  schema,
                  name,
                  definition.variables,
                  true,
                  selected.key,
                );
                if (
                  !variables.length ||
                  selected.sensitive_outputs.some(
                    (path) => path === name || path.startsWith(name + "."),
                  )
                )
                  return null;
                return (
                  <Field key={name} label={name}>
                    <Select
                      label={`خروجی ${name}`}
                      value={output[name] ?? ""}
                      onChange={(target) => setOutput(name, target)}
                      options={[
                        { value: "", label: "ذخیره نشود" },
                        ...variables.map((variable) => ({
                          value: variable.name,
                          label: `${variable.label || variable.name} · ${variable.type}`,
                        })),
                      ]}
                    />
                  </Field>
                );
              },
            )}
            <p className="text-[11px] leading-6 text-muted-foreground">
              فقط مقدارهای ساده و مرجع‌های مجاز به متغیرهای تعریف‌شده متصل
              می‌شوند. مسیرهای تو‌در‌تو و دادهٔ خصوصی قابل اتصال نیستند.
            </p>
          </div>
        </>
      ) : (
        <p className="text-xs leading-6 text-muted-foreground">
          یک Action و نسخهٔ ثبت‌شده انتخاب کنید، سپس ورودی‌ها و خروجی‌ها را متصل
          کنید.
        </p>
      )}
    </div>
  );
}
