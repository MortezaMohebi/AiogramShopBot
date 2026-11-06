"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileDown, FileSpreadsheet, Filter, Layers3, Search, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import {
  groupDataModel, searchDataModel,
} from "@/app/(console)/data-models/actions";
import type {
  FieldOperator, ModelFilter, ModelGroupResult, ModelImportPreview,
  ModelMetadata, ModelSearchResult, TimeGranularity,
} from "@/lib/model-data";

interface Props { metadata: ModelMetadata }
type Format = "csv" | "xlsx";

const OPS: Array<[FieldOperator, string]> = [
  ["contains", "شامل"], ["eq", "برابر"], ["ne", "نابرابر"],
  ["starts", "شروع با"], ["gte", "بزرگ‌تر یا مساوی"],
  ["lte", "کوچک‌تر یا مساوی"], ["in", "یکی از"],
];

const PERIODS: Array<[TimeGranularity, string]> = [
  ["day", "روزانه"], ["week", "هفتگی"],
  ["month", "ماهانه"], ["quarter", "فصلی"], ["year", "سالانه"],
];

const ERRORS: Record<string, string> = {
  invalid_import_columns: "ستون‌ها باید مطابق فایل الگو باشند؛ ستون ناشناخته یا تکراری مجاز نیست.",
  invalid_import_file: "فایل CSV یا XLSX معتبر و حداکثر ۸ مگابایت انتخاب کنید.",
  import_formula_not_allowed: "فایل حاوی فرمول است؛ فرمول‌ها را با مقدار جایگزین کنید.",
  import_too_many_rows: "فایل باید حداکثر هزار سطر داشته باشد.",
  import_identity_required: "برای تطبیق داده‌ها، External Reference یا SKU معتبر لازم است.",
  import_duplicate_key: "یک شناسه در چند سطر فایل تکرار شده است.",
  import_stock_adjustment_required: "برای تغییر موجودی محصول موجود، سند اصلاح انبار ثبت کنید.",
  import_publish_requires_review: "انتشار محصول از طریق فایل امکان‌پذیر نیست.",
  uom_locked: "واحد فروش محصول دارای موجودی یا سابقهٔ خرید را نمی‌توان از طریق فایل تغییر داد.",
  import_identity_conflict: "External Reference و SKU به دو مورد متفاوت اشاره می‌کنند.",
  import_preview_required: "پیش‌نمایش معتبر نیست یا قبلاً استفاده شده است؛ فایل را دوباره بررسی کنید.",
  import_data_changed: "داده‌ها پس از پیش‌نمایش تغییر کرده‌اند؛ فایل را دوباره بررسی کنید.",
  store_access_denied: "به این فروشگاه دسترسی ندارید.",
  import_failed: "ورود اطلاعات انجام نشد؛ نسخهٔ داده و دسترسی‌ها را بررسی کنید.",
};

const MAX_BYTES = 8 * 1024 * 1024;

/** One reusable UI driven entirely by backend ModelRegistry metadata. */
export function ModelDataWorkbench({ metadata }: Props) {
  const router = useRouter();
  const searchable = metadata.fields.filter((item) => item.searchable);
  const sortable = metadata.fields.filter((item) => item.sortable);
  const groupable = metadata.fields.filter((item) => item.groupable);
  const visibleFields = metadata.fields.filter((item) => item.exportable);

  const [field, setField] = useState(
    searchable.find((item) => item.kind === "string")?.key ??
    searchable[0]?.key ?? "id",
  );
  const [op, setOp] = useState<FieldOperator>("contains");
  const [value, setValue] = useState("");
  const [sortBy, setSortBy] = useState(sortable[0]?.key ?? "id");
  const selectedField = searchable.find((item) => item.key === field);
  const textField = selectedField?.kind === "string" || selectedField?.kind === "enum";
  const applicableOps = OPS.filter(([name]) => (
    textField || (name !== "contains" && name !== "starts")
  ));
  const [descending, setDescending] = useState(true);
  const [filters, setFilters] = useState<ModelFilter[]>([]);
  const [searchResult, setSearchResult] = useState<ModelSearchResult | null>(null);
  const [groupField, setGroupField] = useState(groupable[0]?.key ?? "");
  const [period, setPeriod] = useState<TimeGranularity>("month");
  const [groupResult, setGroupResult] = useState<ModelGroupResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState<Format>("xlsx");
  const [preview, setPreview] = useState<ModelImportPreview | null>(null);

  function addFilter() {
    if (filters.length >= 10 || !field) return;
    const raw = value.trim();
    if (!raw) return;
    const parsed = op === "in" ? raw.split(",").map((part) => part.trim()).filter(Boolean) : raw;
    if (Array.isArray(parsed) && (parsed.length < 1 || parsed.length > 20)) {
      setNotice("فیلتر چندمقداری باید یک تا ۲۰ مقدار داشته باشد.");
      return;
    }
    const next: ModelFilter = { field, op, value: parsed };
    setFilters((current) => [...current, next]);
    setValue("");
  }

  async function runSearch(page: number) {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      const response = await searchDataModel(metadata.model, {
        filters, page, page_size: 30, sort_by: sortBy, descending,
      });
      if (!response.ok) {
        setNotice(response.error);
      } else {
        setSearchResult(response.data);
      }
    } catch {
      setNotice("جست‌وجو انجام نشد. اتصال را بررسی و دوباره جست‌وجو کنید.");
    } finally { setBusy(false); }
  }

  async function runGroup() {
    if (busy || !groupField) return;
    setBusy(true);
    setNotice("");
    try {
      const selected = groupable.find((item) => item.key === groupField);
      const response = await groupDataModel(
        metadata.model, groupField,
        selected?.kind === "datetime" ? period : null,
        filters,
      );
      if (!response.ok) setNotice(response.error);
      else setGroupResult(response.data);
    } catch {
      setNotice("گروه‌بندی انجام نشد. اتصال را بررسی و دوباره تلاش کنید.");
    } finally { setBusy(false); }
  }

  async function importFile(mode: "preview" | "apply") {
    if (!file || busy || !metadata.can_import) return;
    if (file.size < 1 || file.size > MAX_BYTES) {
      setNotice(ERRORS.invalid_import_file);
      return;
    }
    if (mode === "apply" && (!preview?.sha256 || !preview.preview_id)) return;
    setBusy(true);
    setNotice("");
    try {
      const challenge = await requestBrowserChallenge();
      const query = new URLSearchParams({
        format, mode,
        ...(mode === "apply" && preview ? {
          hash: preview.sha256, preview_id: preview.preview_id ?? "",
        } : {}),
      });
      const response = await fetch(
        `/api/admin/data-models/${metadata.model}/import?${query}`,
        {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Shop-Login-Challenge": challenge,
          },
          body: file,
          signal: AbortSignal.timeout(60_000),
        },
      );
      const payload = await response.json() as {
        ok?: boolean; result?: ModelImportPreview; code?: string;
      };
      if (!response.ok || !payload.ok || !payload.result) {
        setNotice(ERRORS[payload.code ?? ""] ?? "بررسی فایل موفق نبود؛ فایل یا دسترسی‌ها را بررسی کنید.");
        return;
      }
      if (payload.result.committed) {
        setNotice(`اطلاعات وارد شد: ${payload.result.creates} ایجاد · ${payload.result.updates} به‌روزرسانی`);
        setPreview(null);
        router.refresh();
      } else {
        setPreview(payload.result);
      }
    } catch {
      setNotice("اتصال هنگام ورود اطلاعات قطع شد؛ نتیجه مشخص نیست. پیش از تلاش دوباره، وضعیت داده‌ها را بررسی کنید.");
    } finally { setBusy(false); }
  }

  function downloadUrl(action: "template" | "export", extension: Format) {
    return `/api/admin/data-models/${metadata.model}/${action}?format=${extension}`;
  }

  return <div className="space-y-6" aria-busy={busy}>
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <Filter className="size-5" /> جست‌وجوی داده‌ها
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-[1fr_auto_1fr_auto] lg:items-end">
          <label className="space-y-2 text-sm">فیلد
            <select value={field} onChange={(event) => {
              setField(event.target.value);
              const next = searchable.find((item) => item.key === event.target.value);
              setOp(next?.kind === "string" || next?.kind === "enum" ? "contains" : "eq");
            }}
              className="h-10 w-full rounded-md border bg-background px-3">
              {searchable.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}
            </select>
          </label>
          <label className="space-y-2 text-sm">عملگر
            <select value={op} onChange={(event) => setOp(event.target.value as FieldOperator)}
              className="h-10 rounded-md border bg-background px-3">
              {applicableOps.map(([key, label]) =>
                <option key={key} value={key}>{label}</option>)}
            </select>
          </label>
          <label className="space-y-2 text-sm">عبارت / مقدار
            <Input value={value} onChange={(event) => setValue(event.target.value)}
              placeholder="برای تاریخ از UTC استفاده کنید" maxLength={200} />
          </label>
          <Button type="button" disabled={busy} variant="outline" onClick={addFilter}>
            افزودن فیلتر
          </Button>
        </div>
        {filters.length ? <div className="flex flex-wrap gap-2">
          {filters.map((filter, index) => <button key={index} type="button"
            disabled={busy} onClick={() => setFilters(filters.filter((_, i) => i !== index))}
            className="rounded-lg border px-3 py-2 text-xs hover:bg-muted"
            aria-label={`حذف فیلتر ${metadata.fields.find((item) => item.key === filter.field)?.title ?? filter.field}`}>
            {metadata.fields.find((item) => item.key === filter.field)?.title ?? filter.field} · {OPS.find(([key]) => key === filter.op)?.[1] ?? filter.op} · <bdi>{String(filter.value)}</bdi> ×
          </button>)}
          <Button type="button" size="sm" variant="outline"
            onClick={() => setFilters([])} disabled={busy}>پاک کردن فیلترها</Button>
        </div> : null}
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-2 text-sm">مرتب‌سازی
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}
              className="h-10 rounded-md border bg-background px-3">
              {sortable.map((item) => <option key={item.key} value={item.key}>{item.title}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-2 text-sm">
            <input type="checkbox" checked={descending}
              onChange={(event) => setDescending(event.target.checked)} />
            نزولی
          </label>
          <Button type="button" disabled={busy} onClick={() => void runSearch(1)}>
            <Search className="size-4" /> جست‌وجو
          </Button>
        </div>
        {searchResult ? <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {searchResult.total} نتیجه · صفحه {searchResult.page}
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead><tr className="border-b">
                {visibleFields.map((item) =>
                  <th key={item.key} className="min-w-24 p-2 font-semibold">{item.title}</th>)}
              </tr></thead>
              <tbody>{searchResult.items.map((row, index) =>
                <tr key={String(row.id ?? index)} className="border-b">
                  {visibleFields.map((field) =>
                    <td key={field.key} className="max-w-64 truncate p-2" title={String(row[field.key] ?? "")}>
                      {String(row[field.key] ?? "—")}
                    </td>)}
                </tr>)}</tbody>
            </table>
          </div>
          {!searchResult.items.length ? <p className="text-sm text-muted-foreground">
            {filters.length ? "موردی با این فیلترها پیدا نشد." : "هنوز داده‌ای ثبت نشده است."}
          </p> : null}
          <div className="flex gap-3">
            <Button type="button" variant="outline" disabled={busy || searchResult.page <= 1}
              onClick={() => void runSearch(searchResult.page - 1)}>قبلی</Button>
            <Button type="button" variant="outline" disabled={
              busy || searchResult.page * searchResult.page_size >= searchResult.total
            } onClick={() => void runSearch(searchResult.page + 1)}>بعدی</Button>
          </div>
        </div> : null}
      </CardContent>
    </Card>
    {groupable.length ? <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <Layers3 className="size-5" /> گروه‌بندی داده‌ها
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-2 text-sm">گروه‌بندی بر اساس
            <select value={groupField} onChange={(event) => setGroupField(event.target.value)}
              className="block h-10 min-w-44 rounded-md border bg-background px-3">
              {groupable.map((item) => <option key={item.key} value={item.key}>
                {item.title}
              </option>)}
            </select>
          </label>
          {groupable.find((item) => item.key === groupField)?.kind === "datetime" ?
            <label className="space-y-2 text-sm">بازهٔ زمانی
              <select value={period} onChange={(event) => setPeriod(event.target.value as TimeGranularity)}
                className="block h-10 rounded-md border bg-background px-3">
                {PERIODS.map(([key, label]) =>
                  <option key={key} value={key}>{label}</option>)}
              </select>
            </label> : null}
          <Button type="button" variant="outline" disabled={busy}
            onClick={() => void runGroup()}>گروه‌بندی</Button>
        </div>
        {groupResult ? <div className="overflow-x-auto">
          <p className="mb-2 text-xs text-muted-foreground">
            {groupResult.timezone ? "زمان مبنا: UTC" : "مقادیر گروه‌بندی"}
          </p>
          <table className="w-full max-w-xl text-right text-sm">
            <thead><tr className="border-b"><th className="p-2">مقدار / دوره</th>
              <th className="p-2">تعداد</th></tr></thead>
            <tbody>{groupResult.items.map((item, index) =>
              <tr key={index} className="border-b">
                <td className="p-2" dir="auto">{String(item.bucket ?? "نامشخص")}</td>
                <td className="p-2">{item.count}</td>
              </tr>)}</tbody>
          </table>
          {!groupResult.items.length ? <p className="py-3 text-sm text-muted-foreground">
            داده‌ای برای گروه‌بندی پیدا نشد.
          </p> : null}
        </div> : null}
      </CardContent>
    </Card> : null}

    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <FileDown className="size-5" /> دریافت فایل خروجی
      </CardTitle></CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3">
        {(["xlsx", "csv"] as const).map((kind) =>
          <Button key={kind} asChild variant="outline">
            <a href={downloadUrl("export", kind)}>
              <FileSpreadsheet className="size-4" /> دریافت {kind.toUpperCase()}
            </a>
          </Button>)}
        <p className="text-xs leading-6 text-muted-foreground">
          خروجی شامل فروشگاه‌های فعال و حداکثر ۵۰۰۰ ردیف است. اطلاعات مالی و کلیدهای محرمانه در خروجی نیستند.
        </p>
      </CardContent>
    </Card>

    {metadata.can_import ? <Card>
      <CardHeader><CardTitle className="flex items-center gap-2">
        <Upload className="size-5" /> ورود اطلاعات از فایل
      </CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3">
          {(["xlsx", "csv"] as const).map((kind) =>
            <Button key={kind} asChild variant="outline">
              <a href={downloadUrl("template", kind)}>
                <FileDown className="size-4" /> دریافت الگوی {kind.toUpperCase()}
              </a>
            </Button>)}
        </div>
        <p className="text-xs leading-7 text-muted-foreground">
          ابتدا فایل الگو را دریافت و تکمیل کنید. برای به‌روزرسانی، External Reference یا SKU لازم است و داده‌ها باید متعلق به فروشگاه جاری باشند. مشتریان صرفاً با نام یا تلفن به حساب دیگری متصل نمی‌شوند.
        </p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="block space-y-2 text-sm">نوع فایل
            <select value={format} disabled={busy} onChange={(event) => {
              setFormat(event.target.value as Format);
              setFile(null);
              setPreview(null);
            }} className="block h-10 rounded-md border bg-background px-3">
              <option value="xlsx">Excel (.xlsx)</option>
              <option value="csv">CSV UTF-8</option>
            </select>
          </label>
          <label className="block min-w-48 flex-1 space-y-2 text-sm">
            انتخاب فایل (حداکثر ۸ مگابایت)
            <Input type="file" disabled={busy} accept={format === "xlsx" ? ".xlsx" : ".csv"}
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setPreview(null);
                setNotice("");
              }} />
          </label>
          <Button type="button" disabled={busy || !file} variant="outline"
            onClick={() => void importFile("preview")}>بررسی فایل</Button>
        </div>
        {preview ? <div className="space-y-3 rounded-lg border p-4">
          <p className="text-sm font-semibold">پیش‌نمایش تغییرات — هنوز ذخیره نشده است.</p>
          <p className="text-sm">
            {preview.rows} ردیف · {preview.creates} ایجاد · {preview.updates} به‌روزرسانی
          </p>
          <p className="text-xs leading-6 text-muted-foreground">
            هنگام ذخیره، فایل و داده‌های فعلی دوباره بررسی می‌شوند. هر پیش‌نمایش فقط یک‌بار در همین نشست و فروشگاه قابل استفاده است. انتشار محصول و اصلاح موجودی جداگانه انجام می‌شود.
          </p>
          <Button type="button" disabled={busy || !file}
            onClick={() => void importFile("apply")}>
            ذخیره اطلاعات فایل
          </Button>
        </div> : null}
      </CardContent>
    </Card> : null}
    {notice ? <p role="status" className="rounded-xl border p-3 text-sm leading-7">
      {notice}
    </p> : null}
  </div>;
}
