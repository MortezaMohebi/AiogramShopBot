"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useRuntimeMutation, RuntimeMutationNotice } from "./use-mutation";
import { canApproveAction, canRetryDelivery, recoveryOperations, recoveryLabels } from "@/lib/runtime/state";
import type { ActionJob, OutboxItem, Publication, RecoveryTarget, RecoveryOperation } from "@/lib/runtime/types";
/** Every operation requires a deliberate local confirmation, fresh server auth and exact CAS version. */
function ConfirmOperation({
  label,
  description,
  path,
  payload,
  success,
  danger = false
}: {
  label: string;
  description: string;
  path: string;
  payload: Record<string, unknown>;
  success: string;
  danger?: boolean;
}) {
  const [confirmed, setConfirmed] = useState(false),
    mutation = useRuntimeMutation();
  return <div className="min-w-0 space-y-3 rounded-lg border p-3">
  <p className="text-xs leading-6 text-muted-foreground">
    {description}
  </p>
  <label className="flex items-start gap-2 text-xs leading-6"><input type="checkbox" className="mt-1" checked={confirmed} disabled={mutation.disabled} onChange={e => setConfirmed(e.target.checked)} />{label} را تأیید می‌کنم.</label>
  <Button type="button" variant={danger ? "destructive" : "outline"} size="sm" disabled={!confirmed || mutation.disabled} onClick={() => {
      const operationId = crypto.randomUUID();
      void mutation.execute(path, {
        ...payload,
        operation_id: operationId
      }, success, {
        operationId
      });
    }}>
    {label}
  </Button>
  <RuntimeMutationNotice mutation={mutation} />
</div>;
}
export function RetirePublication({
  publication,
  canPublish
}: {
  publication: Publication;
  canPublish: boolean;
}) {
  if (!canPublish || publication.retired) return null;
  return <ConfirmOperation label="بازنشسته‌کردن انتشار" description="ورودی‌های این انتشار برای اجرای جدید غیرفعال می‌شوند. اجراهای قبلی نسخهٔ خود را حفظ می‌کنند؛ انتشار بازنشسته دوباره فعال نمی‌شود." path={`/publications/${publication.id}/retire`} payload={{}} success="انتشار بازنشسته شد." danger />;
}
export function RetryDelivery({
  item,
  canManage
}: {
  item: OutboxItem;
  canManage: boolean;
}) {
  if (!canRetryDelivery(item, canManage)) return null;
  return <ConfirmOperation label="ثبت تلاش مجدد ارسال" description="سرور شکست قطعی پیش از تحویل را تأیید کرده است. درخواست فقط ارسال را در صف می‌گذارد؛ تحویل هنوز انجام نشده است." path={`/outbox/${item.id}/retry`} payload={{
    expected_attempts: item.expected_attempts
  }} success="تلاش مجدد در صف ارسال ثبت شد." />;
}
export function ApproveAction({
  item,
  canManage
}: {
  item: ActionJob;
  canManage: boolean;
}) {
  if (!canApproveAction(item, canManage)) return null;
  return <ConfirmOperation label="تأیید Action" description="تأیید مسئول برای همین Action ثبت می‌شود. اجرای کار و دریافت رسید مرحله‌ای جداست." path={`/actions/${item.id}/approve`} payload={{
    expected_version: item.expected_version
  }} success="تأیید مسئول ثبت شد؛ نتیجهٔ اجرا را در رسید بررسی کنید." />;
}
export function RecoverRun({
  run,
  canManage
}: {
  run: RecoveryTarget;
  canManage: boolean;
}) {
  const [operation, setOperation] = useState<RecoveryOperation | "">("");
  const allowed = recoveryOperations(run, canManage);
  if (!canManage) return <p className="text-xs leading-6 text-muted-foreground">دسترسی مدیریت Runtime برای بازیابی لازم است.</p>;
  if (!allowed.length) return <p className="text-xs leading-6 text-muted-foreground">عملیات بازیابی در وضعیت فعلی قابل ارائه نیست.</p>;
  return <div className="space-y-4">
  <label className="block space-y-2 text-xs">
    <span>عملیات بازیابی</span>
    <select className="h-10 w-full min-w-0 rounded-md border bg-background px-3 text-sm focus-visible:outline-2 focus-visible:outline-ring" value={operation} onChange={e => setOperation(e.target.value as RecoveryOperation)}>
      <option value="">انتخاب عملیات</option>
      {allowed.map(value => <option key={value} value={value}>
        {recoveryLabels[value]}
      </option>)}
    </select>
  </label>
  {operation && allowed.includes(operation) && <ConfirmOperation key={operation} label={recoveryLabels[operation]} description="سرور وضعیت و نسخهٔ اجرا را دوباره بررسی می‌کند. بازیابی اثر تجاری قبلی را برنمی‌گرداند و Action یا ارسال با نتیجهٔ نامعلوم را تکرار نمی‌کند." path={`/runs/${run.id}/recover`} payload={{
      expected_version: run.lock_version,
      operation
    }} success="عملیات بازیابی ثبت شد؛ وضعیت تازهٔ اجرا را بررسی کنید." danger={["cancel", "mark_failed"].includes(operation)} />}
</div>;
}
