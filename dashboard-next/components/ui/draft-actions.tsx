"use client";

import { LoaderCircle, UploadCloud, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function DraftActions({ dirty, pending, submit, formId, onSave, onDiscard }: {
  dirty: boolean;
  pending?: boolean;
  submit?: boolean;
  formId?: string;
  onSave?: () => void;
  onDiscard: () => void;
}) {
  if (!dirty && !pending) return null;
  const saveLabel = pending ? "در حال ذخیره" : "ذخیرهٔ تغییرات";
  return <div className="inline-flex items-center gap-1" role="group" aria-label="تغییرات ذخیره‌نشده">
    <Button type={submit ? "submit" : "button"} form={formId} size="icon" variant="ghost" title={saveLabel} aria-label={saveLabel}
      disabled={pending} onClick={onSave}>
      {pending ? <LoaderCircle aria-hidden="true" className="motion-safe:animate-spin" /> : <UploadCloud aria-hidden="true" />}
    </Button>
    <Button type="button" size="icon" variant="ghost" title="لغو تغییرات" aria-label="لغو تغییرات"
      disabled={pending} onClick={onDiscard}><X aria-hidden="true" /></Button>
  </div>;
}
