"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { changeStoreState } from "@/app/(console)/stores/actions";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";

type Props = { id: string; name: string; state: "active" | "paused" };

export function StoreStateControl({ id, name, state }: Props) {
  const [open, setOpen] = useState(false);
  const [issue, setIssue] = useState<{ message: string; reauthenticate?: boolean }>();
  const [busy, startTransition] = useTransition();
  const next = state === "paused" ? "active" : "paused";
  const title = next === "active" ? "فعال‌سازی فروشگاه" : "توقف فروشگاه";

  function apply() {
    if (busy) return;
    setIssue(undefined);
    startTransition(async () => {
      try {
        const result = await changeStoreState(id, state, next);
        if (result.ok) setOpen(false);
        else setIssue(result);
      } catch {
        setIssue({ message: "نتیجهٔ تغییر وضعیت مشخص نیست. صفحه را تازه‌سازی کنید." });
      }
    });
  }

  return <>
    <Button type="button" size="sm" variant="outline" aria-haspopup="dialog"
      onClick={() => { setIssue(undefined); setOpen(true); }}>{title}</Button>
    <Dialog open={open} onClose={() => { if (!busy) setOpen(false); }} label={title}>
      <div className="space-y-4 p-5">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="text-sm leading-7">
          {next === "active" ? "فروشگاه آمادهٔ راه‌اندازی می‌شود. دریافت پیام و روش پرداخت هر ربات را جداگانه تنظیم کنید." :
            "فروش این فروشگاه متوقف می‌شود. اطلاعات فروشگاه، سفارش‌ها و تنظیمات ربات‌ها حفظ می‌شوند."}
        </p>
        <p dir="auto" className="break-words rounded-md bg-muted p-3 text-sm">{name}</p>
        {issue ? <p role="alert" className="text-sm text-destructive">{issue.message}</p> : null}
        {issue?.reauthenticate ? <Link href="/account" target="_blank" rel="noopener"
          className="block text-sm underline">تأیید هویت در حساب من (زبانهٔ جدید)</Link> : null}
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" disabled={busy} onClick={() => setOpen(false)}>انصراف</Button>
          <Button type="button" variant={next === "paused" ? "destructive" : "default"}
            disabled={busy} onClick={apply}>{busy ? "در حال ذخیره…" : title}</Button>
        </div>
      </div>
    </Dialog>
  </>;
}
