"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { StudioNav } from "./studio-nav";
import { Select } from "./fields";
import { OperationNotice, useWorkflowOperation } from "./use-operation";
import { errorText, workflowRequest } from "@/lib/workflows/client";
import type { Diff, RevisionPage, WorkflowRecord } from "@/lib/workflows/types";
/** Immutable snapshots may be inspected or appended as a fresh draft revision. */
export function WorkflowVersions({
  initial,
  initialVersions,
}: {
  initial: WorkflowRecord;
  initialVersions: RevisionPage;
}) {
  const [record, setRecord] = useState(initial),
    [versions, setVersions] = useState(initialVersions),
    [left, setLeft] = useState(
      String(initialVersions.items[1]?.revision ?? initial.revision),
    ),
    [right, setRight] = useState(String(initial.revision)),
    [diff, setDiff] = useState<Diff | null>(null),
    [snapshot, setSnapshot] = useState<WorkflowRecord | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const operation = useWorkflowOperation((saved) => {
    setRecord(saved);
    void workflowRequest<RevisionPage>(`/${initial.id}/revisions`)
      .then(setVersions)
      .catch((e) => setError(errorText(e)));
  });
  const compare = async () => {
    setBusy(true);
    setError("");
    try {
      setDiff(
        await workflowRequest<Diff>(
          `/${initial.id}/compare?left=${left}&right=${right}`,
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const inspect = async (revision: number) => {
    setBusy(true);
    setError("");
    try {
      setSnapshot(
        await workflowRequest<WorkflowRecord>(
          `/${initial.id}/revisions/${revision}`,
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const loadPage = async (page: number) => {
    setBusy(true);
    try {
      setVersions(
        await workflowRequest<RevisionPage>(
          `/${initial.id}/revisions?page=${page}`,
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const actionLabels: Record<string, string> = {
    create: "ایجاد",
    save: "ذخیره",
    archive: "بایگانی",
    delete: "حذف",
    restore: "بازیابی",
    duplicate: "ایجاد کپی",
  };
  const options = versions.items.map((v) => ({
    value: String(v.revision),
    label: `r${v.revision} · ${actionLabels[v.action] ?? v.action}`,
  }));
  return (
    <div className="min-w-0 space-y-5">
      <div>
        <h1 className="text-2xl font-bold">نسخه‌ها · {record.name}</h1>
        <p className="mt-2 text-sm leading-7 text-muted-foreground">
          بازیابی، یک نسخهٔ جدید از پیش‌نویس می‌سازد و نسخه‌های قبلی را تغییر نمی‌دهد.
        </p>
      </div>
      <StudioNav id={initial.id} current="versions" />
      <div className="min-w-0 rounded-xl border bg-card p-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-0 flex-1 space-y-2 text-xs">
            نسخهٔ مبنا
            <Select
              label="نسخه مبنا"
              value={left}
              onChange={setLeft}
              options={
                options.some((o) => o.value === left)
                  ? options
                  : [{ value: left, label: `r${left}` }, ...options]
              }
            />
          </label>
          <label className="min-w-0 flex-1 space-y-2 text-xs">
            نسخهٔ مقایسه
            <Select
              label="نسخه مقایسه"
              value={right}
              onChange={setRight}
              options={
                options.some((o) => o.value === right)
                  ? options
                  : [{ value: right, label: `r${right}` }, ...options]
              }
            />
          </label>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void compare()}
          >
            مقایسه
          </Button>
        </div>
        {diff && (
          <div className="mt-5 space-y-3">
            <p className="text-sm" dir="ltr">
              r{diff.left_revision} → r{diff.right_revision}
            </p>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-start text-xs">
                <thead>
                  <tr className="border-b">
                    <th scope="col" className="p-2 text-start">بخش</th>
                    <th scope="col" className="p-2 text-start">افزوده</th>
                    <th scope="col" className="p-2 text-start">حذف</th>
                    <th scope="col" className="p-2 text-start">تغییر</th>
                  </tr>
                </thead>
                <tbody>
                  {(["nodes", "edges", "variables"] as const).map((key) => (
                    <tr key={key} className="border-b">
                      <th scope="row" className="p-2 text-start">{{ nodes: "گره‌ها", edges: "اتصال‌ها", variables: "متغیرها" }[key]}</th>
                      {(["added", "removed", "changed"] as const).map(
                        (change) => (
                          <td
                            key={change}
                            className="max-w-40 break-all p-2"
                            dir="ltr"
                          >
                            {diff[key][change].join(", ") || "—"}
                          </td>
                        ),
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs">
              مشخصات: {diff.metadata_changed.join(", ") || "بدون تغییر"} ·
              چیدمان: {diff.layout_changed ? "تغییر کرده" : "بدون تغییر"} ·
              تعریف فرایند:{" "}
              {diff.definition_changed ? "تغییر کرده" : "بدون تغییر"}
            </p>
          </div>
        )}
      </div>
      <div className="space-y-3">
        {versions.items.map((v) => (
          <article
            key={v.revision}
            className="min-w-0 space-y-3 rounded-xl border bg-card p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="font-semibold">
                نسخهٔ {v.revision}{" "}
                <span className="text-xs font-normal text-muted-foreground">
                  · {actionLabels[v.action] ?? v.action}
                </span>
              </h2>
              <span className="text-xs text-muted-foreground">
                {new Date(v.created_at).toLocaleString("fa-IR", {
                  timeZone: "Asia/Tehran",
                })}
              </span>
            </div>
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">شناسهٔ بررسی یکپارچگی نسخه</summary>
              <p className="mt-2 break-all" dir="ltr">SHA-256: {v.sha256}</p>
            </details>
            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => void inspect(v.revision)}
              >
                مشاهدهٔ نسخه
              </Button>
              {record.can_write && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    operation.status === "busy" ||
                    operation.status === "unknown"
                  }
                  onClick={() =>
                    void operation.run({
                      path: `/${record.id}/restore`,
                      method: "POST",
                      targetId: record.id,
                      payload: {
                        operation_id: crypto.randomUUID(),
                        expected_revision: record.head_revision,
                        revision: v.revision,
                      },
                    })
                  }
                >
                  بازیابی در پیش‌نویس جدید
                </Button>
              )}
            </div>
          </article>
        ))}
      </div>
      <div className="flex gap-3">
        {versions.page > 1 && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void loadPage(versions.page - 1)}
          >
            نسخه‌های جدیدتر
          </Button>
        )}
        {versions.has_more && (
          <Button
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => void loadPage(versions.page + 1)}
          >
            نسخه‌های قدیمی‌تر
          </Button>
        )}
      </div>
      <OperationNotice operation={operation} />
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {snapshot && (
        <section className="min-w-0 rounded-xl border bg-card p-5">
          <div className="flex justify-between gap-3">
            <h2 className="font-semibold">نسخهٔ r{snapshot.revision}</h2>
            <Button variant="ghost" size="sm" onClick={() => setSnapshot(null)}>
              بستن
            </Button>
          </div>
          <pre
            dir="ltr"
            className="mt-4 max-h-[600px] overflow-auto whitespace-pre-wrap break-all rounded bg-muted/40 p-4 text-xs"
          >
            {JSON.stringify(
              {
                name: snapshot.name,
                description: snapshot.description,
                definition: snapshot.definition,
                layout: snapshot.layout,
              },
              null,
              2,
            )}
          </pre>
        </section>
      )}
    </div>
  );
}
