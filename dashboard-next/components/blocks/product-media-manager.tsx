"use client";

import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { Check, FileAudio2, FileImage, FileText, FileVideo2, GripVertical, Trash2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestBrowserChallenge } from "@/lib/browser-challenge";

export interface ProductAsset {
  id: number;
  filename: string;
  size_bytes: number;
  kind: string;
  mime_type: string;
  caption: string;
  position: number;
  is_published: boolean;
}

const TYPES = new Set([
  "image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf",
  "video/mp4", "audio/mpeg", "audio/ogg",
]);
const MAX_FILES = 10;
const MAX_FILE_BYTES = 50_000_000;
const MAX_PHOTO_BYTES = 10_000_000;
const ACCEPT = [...TYPES].join(",");

/**
 * Multi-file drop zone with independent single-file uploads. The server
 * determines type from bytes, applies per-provider limits, and keeps new
 * assets unpublished until an editor approves them.
 */
export function ProductMediaManager({
  productId, initial,
}: { productId: number; initial: ProductAsset[] }) {
  const [items, setItems] = useState(initial);
  const [working, setWorking] = useState(false);
  const [hover, setHover] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const chooser = useRef<HTMLInputElement>(null);
  const [captions, setCaptions] = useState<Record<number, string>>({});

  async function refresh() {
    const response = await fetch(`/api/admin/product-media?product_id=${productId}`, {
      credentials: "same-origin", cache: "no-store", redirect: "error",
      signal: AbortSignal.timeout(15_000),
    });
    const result = await response.json() as { ok?: boolean; items?: ProductAsset[] };
    if (!response.ok || !result.ok || !Array.isArray(result.items)) throw new Error("دریافت رسانه‌ها انجام نشد.");
    setItems(result.items);
  }

  function validate(file: File): string | null {
    if (!TYPES.has(file.type)) return `فرمت «${file.name}» پشتیبانی نمی‌شود.`;
    if (file.size === 0) return `فایل «${file.name}» خالی است.`;
    if (file.size > (["image/png", "image/jpeg", "image/webp"].includes(file.type) ? MAX_PHOTO_BYTES : MAX_FILE_BYTES)) {
      return `حجم «${file.name}» بیش از سقف مجاز است.`;
    }
    return null;
  }

  async function upload(files: FileList | File[]) {
    if (working) return;
    const chosen = Array.from(files);
    if (!chosen.length) return;
    if (chosen.length > MAX_FILES) {
      setNotice("در هر نوبت حداکثر ۱۰ فایل انتخاب کنید."); return;
    }
    const problem = chosen.map(validate).find((value) => value !== null);
    if (problem) { setNotice(problem); return; }
    setWorking(true);
    const failures: string[] = [];
    let uploaded = 0;
    try {
      for (const file of chosen) {
        try {
          // One request per media file keeps within the backend's 50 MB cap.
          const form = new FormData();
          form.set("product_id", String(productId));
          form.set("position", "0");
          form.set("caption", "");
          form.set("file", file, file.name);
          const response = await fetch("/api/admin/upload?target=product&response=json", {
            method: "POST", body: form, credentials: "same-origin",
            cache: "no-store", redirect: "error", signal: AbortSignal.timeout(125_000),
          });
          const payload = await response.json() as { ok?: boolean; code?: string };
          if (!response.ok || payload.ok !== true) throw new Error(payload.code ?? "upload");
          uploaded++;
        } catch {
          failures.push(file.name);
        }
      }
      await refresh();
      setNotice(failures.length
        ? `${uploaded} فایل ذخیره شد؛ ارسال ${failures.length} فایل انجام نشد: ${failures.join("، ")}`
        : `${uploaded} فایل خصوصی ذخیره شد. پس از بررسی هر فایل، آن را منتشر کنید.`);
    } catch {
      setNotice("پس از آپلود، به‌روزرسانی فهرست ممکن نشد؛ صفحه را تازه‌سازی کنید.");
    } finally {
      if (chooser.current) chooser.current.value = "";
      setWorking(false);
    }
  }

  async function mutate(item: ProductAsset, method: "PATCH" | "DELETE", body: Record<string, unknown> | null) {
    if (working) return;
    if (method === "DELETE" && !window.confirm("رسانهٔ منتشرنشده حذف شود؟ این عملیات قابل بازگشت نیست.")) return;
    setWorking(true); setNotice(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch(`/api/admin/product-media/${item.id}`, {
        method, credentials: "same-origin", cache: "no-store", redirect: "error",
        headers: { ...(body ? { "Content-Type": "application/json" } : {}), "X-Shop-Login-Challenge": challenge },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(25_000),
      });
      const result = await response.json() as { ok?: boolean };
      if (!response.ok || !result.ok) throw new Error("تغییر انجام نشد؛ ممکن است وضعیت رسانه تغییر کرده باشد.");
      await refresh();
      setNotice("تغییرات رسانه ثبت شد.");
    } catch (failure) {
      setNotice(failure instanceof Error ? failure.message : "ارتباط با سرور برقرار نشد.");
    } finally {
      setWorking(false);
    }
  }

  function onFiles(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) void upload(event.target.files);
  }
  function onDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault(); setHover(false);
    if (event.dataTransfer.files.length) void upload(event.dataTransfer.files);
  }
  const size = (value: number) => `${(value / 1_000_000).toLocaleString("fa-IR", { maximumFractionDigits: 1 })} MB`;
  const kinds = {
    photo: <FileImage className="size-5" />,
    document: <FileText className="size-5" />,
    video: <FileVideo2 className="size-5" />,
    audio: <FileAudio2 className="size-5" />,
  };

  return <div className="space-y-5">
    <div onDragEnter={(event) => { event.preventDefault(); setHover(true); }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => { event.preventDefault(); setHover(false); }}
      onDrop={onDrop}
      className={`rounded-xl border-2 border-dashed px-5 py-9 text-center transition-colors ${hover ? "border-primary bg-primary/10" : "border-border bg-muted/20"}`}
      aria-label="ناحیهٔ رها کردن تصاویر و فایل‌ها">
      <UploadCloud className="mx-auto mb-3 size-8 text-primary" aria-hidden="true" />
      <p className="font-semibold">رسانه‌ها را اینجا رها کنید</p>
      <p className="my-2 text-xs leading-7 text-muted-foreground">تصویر تا ۱۰ MB؛ ویدیو، صدا، PDF و GIF تا ۵۰ MB. حداکثر ۱۰ فایل در هر نوبت.</p>
      <input ref={chooser} type="file" accept={ACCEPT} multiple className="sr-only" onChange={onFiles} disabled={working} aria-label="انتخاب چند رسانه" />
      <Button type="button" variant="outline" disabled={working} onClick={() => chooser.current?.click()}>
        <UploadCloud className="size-4" /> {working ? "در حال بارگذاری…" : "انتخاب چند فایل"}
      </Button>
    </div>
    {notice ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm leading-7">{notice}</p> : null}
    <div className="space-y-3">
      {items.map((item) => <div key={item.id} className="rounded-lg border p-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-muted-foreground">{kinds[item.kind as keyof typeof kinds] ?? <FileText className="size-5" />}</span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold" dir="auto">{item.filename}</p>
            <p className="text-xs text-muted-foreground">{size(item.size_bytes)} · {item.is_published ? "منتشرشده" : "پیش‌نویس خصوصی"}</p>
          </div>
          <a href={`/api/admin/preview/product/${item.id}`} target="_blank" rel="noopener noreferrer"
            className="rounded-md border px-3 py-2 text-xs underline underline-offset-4">نمایش فایل</a>
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-[minmax(0,1fr)_6rem]">
          <label className="space-y-1 text-xs">شرح رسانه
            <Input value={captions[item.id] ?? item.caption} maxLength={2000} disabled={working}
              onChange={(event) => setCaptions((old) => ({ ...old, [item.id]: event.target.value }))} />
          </label>
          <label className="space-y-1 text-xs">ترتیب
            <Input type="number" min={0} max={1000000} defaultValue={item.position} disabled={working}
              aria-label={`ترتیب ${item.filename}`} id={`media-position-${item.id}`} />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={working}
            onClick={() => {
              const order = Number((document.getElementById(`media-position-${item.id}`) as HTMLInputElement | null)?.value ?? item.position);
              void mutate(item, "PATCH", { caption: captions[item.id] ?? item.caption, position: order });
            }}>ذخیره شرح و ترتیب</Button>
          <Button type="button" variant="outline" size="sm" disabled={working}
            onClick={() => void mutate(item, "PATCH", { is_published: !item.is_published })}>
            {item.is_published ? "لغو انتشار" : <><Check className="size-4" /> تأیید انتشار</>}
          </Button>
          {!item.is_published ? <Button type="button" variant="destructive" size="sm" disabled={working}
            onClick={() => void mutate(item, "DELETE", null)}><Trash2 className="size-4" /> حذف پیش‌نویس</Button> : null}
        </div>
      </div>)}
      {!items.length ? <p className="text-sm text-muted-foreground">رسانه‌ای ثبت نشده است.</p> : null}
    </div>
  </div>;
}
