"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { ValueField, Select } from "./fields";
import { parseScalar } from "@/lib/workflows/scalar";
import type { Scalar, Variable } from "@/lib/workflows/types";
/** Catalog json fields are the finite Scalar union, never arbitrary JSON or code. */
export function ScalarField({
  label,
  value,
  onChange,
  variable
}: {
  label: string;
  value: Scalar;
  onChange: (value: Scalar) => void;
  variable?: Variable;
}) {
  const [mode, setMode] = useState("typed"),
    [raw, setRaw] = useState(JSON.stringify(value ?? null)),
    [error, setError] = useState("");
  const inferred = typeof value === "boolean" ? "boolean" : typeof value === "number" ? "integer" : value && typeof value === "object" ? `${value.kind}_ref` as const : "string";
  const [kind, setKind] = useState<Variable["type"]>(inferred);
  return <div className="space-y-3">
  <Select label={`${label} · شیوهٔ ورود`} value={mode} options={[{
      value: "typed",
      label: "مقدار نوع‌دار"
    }, {
      value: "json",
      label: "JSON Scalar"
    }]} onChange={next => {
      setMode(next);
      setRaw(JSON.stringify(value ?? null));
      setError("");
    }} />
  {mode === "typed" ? <>
    {!variable && <Select label={`${label} · نوع مقدار`} value={kind} options={[{
        value: "string",
        label: "متن"
      }, {
        value: "integer",
        label: "عدد صحیح"
      }, {
        value: "boolean",
        label: "درست / نادرست"
      }, {
        value: "product_ref",
        label: "ارجاع محصول"
      }, {
        value: "category_ref",
        label: "ارجاع دسته‌بندی"
      }, {
        value: "order_ref",
        label: "ارجاع سفارش"
      }, {
        value: "customer_ref",
        label: "ارجاع مشتری"
      }]} onChange={type => {
        setKind(type as Variable["type"]);
        onChange(null);
      }} />}
    <ValueField label={label} type={variable?.type ?? kind} choices={variable?.choices} value={value ?? null} onChange={onChange} />
  </> : <>
    <Input dir="ltr" aria-label={`${label} · JSON Scalar`} aria-invalid={!!error} maxLength={8192} value={raw} onChange={event => {
        const next = event.target.value;
        setRaw(next);
        try {
          onChange(parseScalar(next));
          setError("");
        } catch {
          setError("مقدار باید متن JSON، عدد صحیح، مقدار بولی، null یا ارجاع نوع‌دار با شناسهٔ صحیح باشد.");
        }
      }} />
    {error && <p role="alert" className="text-xs leading-6 text-destructive">{error} مقدار معتبر قبلی حفظ شده است.</p>}
  </>}
  <p className="text-xs leading-6 text-muted-foreground">فقط مقدار ثابت ذخیره می‌شود. ارجاع شامل نوع و شناسه است؛ عبارت اجرایی پذیرفته نمی‌شود.</p>
</div>;
}
