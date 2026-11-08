"use client";

import { ReauthenticateButton } from "@/components/blocks/reauthentication";
import { Plus } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState, useTransition } from "react";
import { createStore } from "@/app/(console)/stores/actions";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { normalizeStoreName } from "@/lib/store-name";

export function StoreCreateWizard() {
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [review, setReview] = useState(false);
  const [notice, setNotice] = useState("");
  const [reauthenticate, setReauthenticate] = useState(false);
  const [created, setCreated] = useState("");
  const [busy, startTransition] = useTransition();
  const title = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (review) title.current?.focus();
  }, [review]);

  function open() {
    setName("");
    setReview(false);
    setNotice("");
    setReauthenticate(false);
    setCreated("");
    setSlug(`store-${crypto.randomUUID()}`);
  }

  function close() {
    if (!busy) setSlug("");
  }

  function showReview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeStoreName(name);
    if (!normalized) {
      setNotice("نام باید ۲ تا ۱۶۰ نویسه و دست‌کم یک حرف داشته باشد. از خط جدید یا نویسه‌های کنترلی استفاده نکنید.");
      return;
    }
    setName(normalized);
    setNotice("");
    setReview(true);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !review || !slug) return;
    setNotice("");
    setReauthenticate(false);
    startTransition(async () => {
      try {
        const result = await createStore(name, slug);
        if (!result.ok) {
          setNotice(result.message);
          setReauthenticate(result.reauthenticate === true);
          return;
        }
        setCreated(name);
        setSlug("");
      } catch {
        setNotice("نتیجهٔ ثبت مشخص نیست. ابتدا فهرست فروشگاه‌ها را بررسی کنید.");
      }
    });
  }

  return <div className="space-y-3">
    <Button type="button" onClick={open} aria-haspopup="dialog">
      <Plus aria-hidden="true" className="size-4" /> ساخت فروشگاه
    </Button>
    {created ? <p role="status" className="text-sm">فروشگاه «{created}» ایجاد شد.</p> : null}
    <Dialog open={Boolean(slug)} label="ساخت فروشگاه" onClose={close}>
      <div className="space-y-4 p-5">
        <p className="text-xs text-muted-foreground">مرحلهٔ {review ? "۲" : "۱"} از ۲</p>
        <h2 ref={title} tabIndex={-1} className="text-lg font-semibold">
          {review ? "بازبینی فروشگاه" : "نام شرکت یا فروشگاه"}
        </h2>
        {!review ? <form className="space-y-4" onSubmit={showReview}>
          <label htmlFor="new-store-name" className="block space-y-2 text-sm">
            <span>نام شرکت یا فروشگاه</span>
            <Input id="new-store-name" name="name" dir="auto" autoComplete="organization"
              aria-invalid={Boolean(notice)} aria-describedby={notice ? "new-store-error" : undefined}
              value={name} onChange={(event) => { setName(event.target.value); setNotice(""); }}
              required />
          </label>
          {notice ? <p id="new-store-error" role="alert" className="text-sm text-destructive">{notice}</p> : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit">بازبینی</Button>
            <Button type="button" variant="outline" onClick={close}>انصراف</Button>
          </div>
        </form> : <form className="space-y-4" onSubmit={submit}>
          <p className="break-words rounded-md bg-muted p-3 text-sm"><bdi>{name}</bdi></p>
          <p className="text-sm leading-7 text-muted-foreground">
            فروشگاه با فروش متوقف ایجاد می‌شود. برای دیدن تنظیمات آن، فروشگاه را از انتخاب‌گر بالای صفحه انتخاب کنید.
          </p>
          {notice ? <p role="alert" className="text-sm text-destructive">{notice}</p> : null}
          {reauthenticate ? <ReauthenticateButton /> : null}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" disabled={busy}>{busy ? "در حال ساخت…" : "ایجاد فروشگاه"}</Button>
            <Button type="button" variant="outline" disabled={busy}
              onClick={() => { setNotice(""); setReview(false); }}>بازگشت</Button>
            <Button type="button" variant="ghost" disabled={busy} onClick={close}>انصراف</Button>
          </div>
        </form>}
      </div>
    </Dialog>
  </div>;
}
