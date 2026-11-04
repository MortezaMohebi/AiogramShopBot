"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { requestBrowserChallenge } from "@/lib/browser-challenge";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 50_000_000;
const VALID = /\.(pdf|zip|epub|docx|xlsx|png|jpg|webp|gif|mp4|mp3|ogg|txt)$/i;

/** Only the encrypted dashboard bridge may upload a private paid asset. */
export function DigitalFileUploader({ productId }: { productId: number }) {
  const input = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function upload(): Promise<void> {
    const file = input.current?.files?.[0];
    if (busy || !file) return;
    if (!VALID.test(file.name) || file.size < 1 || file.size > MAX_BYTES) {
      setMessage("پسوند یا حجم فایل مجاز نیست (حداکثر ۵۰ مگابایت).");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const challenge = await requestBrowserChallenge();
      const data = new FormData();
      data.set("file", file, file.name);
      const response = await fetch(`/api/admin/digital-assets/${productId}`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          Accept: "application/json",
          "X-Shop-Login-Challenge": challenge,
        },
        body: data,
        signal: AbortSignal.timeout(120_000),
      });
      const result = await response.json() as { ok?: boolean; code?: string };
      if (!response.ok || result.ok !== true) {
        throw new Error(result.code === "reauth"
          ? "احراز هویت مجدد لازم است."
          : "ذخیره فایل خصوصی انجام نشد؛ وضعیت Store و فایل را بررسی کنید.");
      }
      if (input.current) input.current.value = "";
      setMessage("فایل خصوصی ثبت شد. دسترسی قبل از پرداخت وجود ندارد.");
      router.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "خطا در ارسال فایل.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="space-y-3">
    <label className="block space-y-2 text-sm">
      فایل خریداری‌شده (خارج از Media عمومی و CDN)
      <input ref={input} type="file"
        className="block w-full rounded-md border bg-background p-2"
        accept=".pdf,.zip,.epub,.docx,.xlsx,.png,.jpg,.webp,.gif,.mp4,.mp3,.ogg,.txt" />
    </label>
    <Button type="button" disabled={busy} onClick={() => void upload()}>
      {busy ? "در حال ارسال امن..." : "ذخیره فایل خصوصی"}
    </Button>
    {message ? <p role="status" className="text-sm">{message}</p> : null}
  </div>;
}
