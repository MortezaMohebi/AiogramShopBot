"use client";

import {
  type ChangeEvent,
  type DragEvent,
  useId,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import {
  FileAudio, FileImage, FileText,
  FileVideo, LoaderCircle, Trash2, UploadCloud,
} from "lucide-react";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export interface ProductFile {
  id: number;
  filename: string;
  kind: "photo" | "video" | "audio" | "document";
  mime_type: string;
  size_bytes: number;
  caption: string | null;
  is_published: boolean;
}

const PHOTO_LIMIT = 10_000_000;
const MEDIA_LIMIT = 50_000_000;
const ACCEPTED = new Set([
  "image/png", "image/jpeg", "image/webp", "image/gif",
  "video/mp4", "audio/mpeg", "audio/ogg", "application/pdf",
]);

const formError: Record<string, string> = {
  security_check_failed: "نشست امنیتی معتبر نیست؛ صفحه را دوباره باز کنید.",
  permission_denied: "اجازهٔ مدیریت رسانه ندارید.",
  size: "حجم فایل از سقف مجاز بیشتر است.",
  file: "نوع یا محتوای فایل مجاز نیست.",
  conflict: "این فایل در وضعیت فعلی قابل حذف نیست؛ ابتدا لغو انتشار کنید.",
  upload: "بارگذاری کامل نشد؛ وضعیت رسانه را بررسی کنید.",
  service_unavailable: "سرویس رسانه در دسترس نیست. وضعیت را بررسی کنید.",
  network_unavailable: "ارتباط با سرویس رسانه برقرار نشد.",
};

/** Keep transport errors out of user copy and preserve an uncertain result. */
function mediaError(error: unknown): string {
  if (error instanceof Error) {
    if (Object.hasOwn(formError, error.message)) return formError[error.message];
    if (error.name === "Error") return error.message;
  }
  return "نتیجهٔ تغییر رسانه مشخص نشد. پیش از تکرار، فهرست رسانه‌ها را بررسی کنید.";
}

const maxSize = (file: File) => file.type.startsWith("image/")
  ? PHOTO_LIMIT : MEDIA_LIMIT;

function validateFile(file: File): string | null {
  if (!ACCEPTED.has(file.type)) {
    return "فرمت «" + file.name + "» مجاز نیست.";
  }
  if (file.size <= 0 || file.size > maxSize(file)) {
    return "حجم «" + file.name + "» نامعتبر است.";
  }
  return null;
}

function KindIcon({ kind }: { kind: ProductFile["kind"] }) {
  const Icon = kind === "photo"
    ? FileImage : kind === "video"
      ? FileVideo : kind === "audio"
        ? FileAudio : FileText;
  return <Icon aria-hidden="true" className="size-5 shrink-0" />;
}

/**
 * Product-scoped drag/drop and multi-file upload.
 *
 * Files are transmitted individually because FastAPI enforces an independent
 * 50-MB request budget and each upload has its own idempotent DB record.
 * New assets are unpublished by default.
 */
export function ProductMediaPanel({
  productId,
  initial,
}: {
  productId: number;
  initial: ProductFile[];
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [files, setFiles] = useState<File[]>([]);
  const [caption, setCaption] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [completed, setCompleted] = useState(0);

  function choose(value: FileList | File[]) {
    const selected = Array.from(value);
    setNotice(null);
    if (selected.length > 12) {
      setNotice("در هر نوبت حداکثر ۱۲ فایل انتخاب کنید.");
      return;
    }
    for (const file of selected) {
      const message = validateFile(file);
      if (message) {
        setNotice(message);
        return;
      }
    }
    setFiles(selected);
    setCompleted(0);
  }

  function dropped(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    choose(event.dataTransfer.files);
  }

  async function upload() {
    if (busy || !files.length) return;
    setBusy(true);
    setNotice(null);
    let succeeded = 0;
    try {
      for (const file of files) {
        const challenge = await requestBrowserChallenge();
        const form = new FormData();
        form.set("product_id", String(productId));
        form.set("caption", caption.trim().slice(0, 2000));
        form.set("file", file, file.name);
        const response = await fetch("/api/admin/upload?target=product", {
          method: "POST",
          credentials: "same-origin",
          redirect: "error",
          cache: "no-store",
          headers: {
            Accept: "application/json",
            "X-Shop-Login-Challenge": challenge,
          },
          body: form,
          signal: AbortSignal.timeout(120_000),
        });
        if (!(response.headers.get("content-type") ?? "").includes("application/json")) {
          throw new Error("سرویس بارگذاری پاسخ معتبر برنگرداند.");
        }
        const result = await response.json() as { ok?: boolean; code?: string };
        if (!response.ok || result.ok !== true) {
          throw new Error(formError[result.code ?? ""] ?? "بارگذاری فایل کامل نشد.");
        }
        succeeded += 1;
        setCompleted(succeeded);
      }
      setFiles([]);
      if (input.current) input.current.value = "";
      setCaption("");
      setNotice("فایل‌های جدید خصوصی ذخیره شدند؛ برای نمایش به مشتری انتشارشان را تأیید کنید.");
      router.refresh();
    } catch (error) {
      setNotice(mediaError(error));
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  async function mutate(item: ProductFile, action: "publish" | "delete") {
    if (busy) return;
    if (action === "delete") {
      if (item.is_published) {
        setNotice("ابتدا انتشار فایل را لغو کنید.");
        return;
      }
      if (!window.confirm("فایل «" + item.filename + "» برای همیشه حذف شود؟")) {
        return;
      }
    }
    setBusy(true);
    setNotice(null);
    try {
      const challenge = await requestBrowserChallenge();
      const response = await fetch("/api/admin/product-media/" + item.id, {
        method: action === "delete" ? "DELETE" : "PATCH",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
          ...(action === "publish" ? { "Content-Type": "application/json" } : {}),
        },
        ...(action === "publish"
          ? { body: JSON.stringify({ is_published: !item.is_published }) }
          : {}),
        signal: AbortSignal.timeout(20_000),
      });
      const result = await response.json() as { ok?: boolean; code?: string };
      if (!response.ok || !result.ok) {
        throw new Error(formError[result.code ?? ""] ?? "عملیات کامل نشد.");
      }
      setNotice(action === "delete"
        ? "فایل پیش‌نویس حذف شد."
        : "وضعیت انتشار تغییر کرد.");
      router.refresh();
    } catch (error) {
      setNotice(mediaError(error));
    } finally {
      setBusy(false);
    }
  }

  function filesChanged(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) choose(event.target.files);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>رسانه‌های این محصول</CardTitle>
        <CardDescription>
          فایل‌های جدید تا زمان تأیید انتشار به مشتری نمایش داده نمی‌شوند.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {notice ? <p role="status" className="rounded-md bg-muted p-3 text-sm">{notice}</p> : null}
        <div
          onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={dropped}
          className={
            "rounded-xl border-2 border-dashed p-7 text-center transition-colors " +
            (dragging ? "border-primary bg-accent" : "border-border")
          }
        >
          <UploadCloud aria-hidden="true" className="mx-auto mb-3 size-9 text-primary" />
          <p className="mb-3 text-sm">فایل‌ها را اینجا رها کنید یا انتخاب کنید.</p>
          <label
            htmlFor={id}
            className="inline-flex cursor-pointer items-center rounded-md border bg-background px-4 py-2 text-sm hover:bg-accent focus-within:outline-2"
          >
            انتخاب فایل‌ها
          <input
            ref={input}
            id={id}
            className="sr-only"
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp,image/gif,video/mp4,audio/mpeg,audio/ogg,application/pdf"
            onChange={filesChanged}
            disabled={busy}
          />
          </label>
          <p className="mt-3 text-xs text-muted-foreground">
            تصاویر حداکثر ۱۰ مگابایت؛ سایر رسانه‌ها حداکثر ۵۰ مگابایت
          </p>
        </div>
        {files.length ? (
          <div className="space-y-3 rounded-lg border p-4">
            <p className="text-sm font-semibold">{files.length} فایل آمادهٔ بارگذاری</p>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {files.map((file, index) =>
                <li key={file.name + ":" + index} dir="ltr" className="break-all">
                  {file.name} ({(file.size / 1_000_000).toFixed(1)} MB)
                </li>)}
            </ul>
            <label className="block space-y-2 text-sm">
              توضیح مشترک فایل‌ها (اختیاری)
              <input
                value={caption}
                onChange={(event) => setCaption(event.target.value)}
                maxLength={2000}
                className="h-10 w-full rounded-md border border-input bg-background px-3"
                disabled={busy}
              />
            </label>
            <Button type="button" onClick={() => void upload()} disabled={busy}>
              {busy ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" />
                : <UploadCloud aria-hidden="true" className="size-4" />}
              {busy
                ? "در حال بارگذاری " + completed + " از " + files.length
                : "بارگذاری خصوصی فایل‌ها"}
            </Button>
          </div>
        ) : null}
        {initial.length ? (
          <div className="space-y-2">
            {initial.map((item) => (
              <div
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <KindIcon kind={item.kind} />
                  <div className="min-w-0">
                    <p dir="ltr" className="max-w-xs break-all text-xs font-semibold">{item.filename}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.is_published ? "قابل نمایش به مشتری" : "خصوصی"}
                      {" · "}{(item.size_bytes / 1_000_000).toFixed(1)} MB
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <a
                    target="_blank"
                    rel="noopener noreferrer"
                    href={"/api/admin/preview/product/" + item.id}
                    className="text-xs text-primary underline"
                  >
                    پیش‌نمایش
                  </a>
                  <Button
                    type="button" size="sm" variant="outline"
                    disabled={busy}
                    onClick={() => void mutate(item, "publish")}
                  >
                    {item.is_published ? "لغو انتشار" : "تأیید انتشار"}
                  </Button>
                  {!item.is_published ? (
                    <Button
                      type="button" size="sm" variant="destructive"
                      disabled={busy}
                      onClick={() => void mutate(item, "delete")}
                    >
                      <Trash2 aria-hidden="true" className="size-4" />
                      حذف
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">هنوز رسانه‌ای برای این محصول وجود ندارد.</p>
        )}
      </CardContent>
    </Card>
  );
}
