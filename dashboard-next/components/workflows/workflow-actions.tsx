"use client";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { OperationNotice, useWorkflowOperation } from "./use-operation";
import type { WorkflowRecord } from "@/lib/workflows/types";
/** CAS includes the displayed revision; unsaved/newer changes cannot be silently archived. */
export function WorkflowActions({
  record,
  disabled = false,
}: {
  record: WorkflowRecord;
  disabled?: boolean;
}) {
  const router = useRouter();
  const operation = useWorkflowOperation(() =>
    router.push("/studio/workflows?status=all"),
  );
  const busy =
    disabled || operation.status === "busy" || operation.status === "unknown";
  return (
    <section className="space-y-4 rounded-xl border bg-card p-5">
      <h2 className="font-semibold">مدیریت پیش‌نویس</h2>
      <p className="text-xs leading-6 text-muted-foreground">
        ابتدا تغییرات را ذخیره کنید. بایگانی یا حذف فقط با Revision
        نمایش‌داده‌شده انجام می‌شود؛ تاریخچه برای Restore حفظ خواهد شد.
      </p>
      <div className="flex flex-wrap gap-3">
        {record.can_write && (
          <Button asChild variant="outline" size="sm">
            <Link href={`/studio/workflows/new?source=${record.id}`}>
              کپی به فرایند جدید
            </Link>
          </Button>
        )}
        {record.can_write && record.status === "draft" && (
          <>
            <Button
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() =>
                void operation.run({
                  path: `/${record.id}/archive`,
                  method: "POST",
                  targetId: record.id,
                  payload: {
                    operation_id: crypto.randomUUID(),
                    expected_revision: record.revision,
                  },
                })
              }
            >
              بایگانی
            </Button>
            <Button
              variant="destructive"
              size="sm"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    "پیش‌نویس از فهرست فعال حذف شود؟ نسخه‌ها برای بازیابی حفظ می‌شوند.",
                  )
                )
                  void operation.run({
                    path: `/${record.id}`,
                    method: "DELETE",
                    targetId: record.id,
                    payload: {
                      operation_id: crypto.randomUUID(),
                      expected_revision: record.revision,
                    },
                  });
              }}
            >
              حذف پیش‌نویس
            </Button>
          </>
        )}
      </div>
      <OperationNotice operation={operation} />
    </section>
  );
}
