"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Field, Select } from "./fields";
import { OperationNotice, useWorkflowOperation } from "./use-operation";
export function CreateWorkflowForm({
  source,
}: {
  source?: { id: string; name: string; description: string };
}) {
  const router = useRouter();
  const [name, setName] = useState(source ? `${source.name} (کپی)` : ""),
    [key, setKey] = useState(""),
    [description, setDescription] = useState(source?.description ?? ""),
    [template, setTemplate] = useState("blank");
  const operation = useWorkflowOperation((record) =>
    router.push(`/studio/workflows/${record.id}`),
  );
  const busy = operation.status === "busy" || operation.status === "unknown";
  return (
    <form
      className="max-w-2xl space-y-5 rounded-xl border bg-card p-6"
      onSubmit={(e) => {
        e.preventDefault();
        if (busy) return;
        const id = crypto.randomUUID();
        void operation.run({
          path: source ? `/${source.id}/duplicate` : "",
          method: "POST",
          targetId: id,
          payload: {
            id,
            operation_id: crypto.randomUUID(),
            key,
            name,
            description,
            ...(!source ? { template } : {}),
          },
        });
      }}
    >
      <fieldset disabled={busy} className="space-y-5">
        <Field label="نام فرایند">
          <Input
            aria-label="نام فرایند جدید"
            required
            minLength={1}
            maxLength={160}
            autoComplete="off"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field
          label="کلید پایدار"
          hint="با حرف کوچک انگلیسی شروع شود؛ فقط حروف کوچک، عدد، خط تیره و زیرخط."
        >
          <Input
            aria-label="کلید فرایند"
            dir="ltr"
            required
            pattern="[a-z][a-z0-9_-]{0,63}"
            maxLength={64}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="request_return"
          />
        </Field>
        <Field label="توضیحات">
          <Textarea
            aria-label="توضیحات فرایند جدید"
            value={description}
            maxLength={4000}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Field>
        {!source && (
          <Field label="نقطهٔ شروع">
            <Select
              label="الگوی شروع"
              value={template}
              onChange={setTemplate}
              options={[
                { value: "blank", label: "فرایند خالی" },
                { value: "wholesale_application", label: "درخواست همکاری عمده" },
                {
                  value: "return_request",
                  label: "نمونهٔ Request Return · فقط پیش‌نویس و شبیه‌سازی",
                },
              ]}
            />
          </Field>
        )}
        <p className="text-sm leading-7 text-muted-foreground">
          فرایند در فروشگاه جاری ذخیره می‌شود. پس از ساخت، می‌توانید ربات‌ها و
          پلتفرم‌های مجاز را انتخاب کنید.
        </p>
        <Button type="submit">
          {busy ? "در حال ثبت…" : source ? "ساخت کپی مستقل" : "ساخت پیش‌نویس"}
        </Button>
      </fieldset>
      <OperationNotice operation={operation} />
    </form>
  );
}
