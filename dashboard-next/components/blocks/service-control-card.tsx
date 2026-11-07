"use client";

import { useState } from "react";
import { useFormStatus } from "react-dom";
import Link from "next/link";
import { changeService } from "@/app/(console)/services/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { prerequisiteMessages, services, type ServiceControl } from "@/lib/service-controls";

type Choice = "enable" | "disable" | "default";
const labels: Record<Choice, string> = {
  enable: "فعال کردن",
  disable: "متوقف کردن",
  default: "بازگشت به پیش‌فرض",
};

function ConfirmButtons({ choice, close }: { choice: Choice; close: () => void }) {
  const { pending } = useFormStatus();
  return <div className="flex flex-wrap gap-2">
    <Button type="submit" disabled={pending}>{pending ? "در حال ذخیره…" : labels[choice]}</Button>
    <Button type="button" variant="outline" onClick={close} disabled={pending}>انصراف</Button>
  </div>;
}

export function ServiceControlCard({ service }: { service: ServiceControl }) {
  const [choice, setChoice] = useState<Choice | null>(null);
  const item = services[service.key];
  const blocked = service.blocked_reason !== null;
  const requested = service.override ?? service.default;
  const next = requested ? "disable" : "enable";

  return <Card className="flex flex-col">
    <CardHeader>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardTitle>{item.title}</CardTitle>
        <Badge tone={service.enabled ? "success" : "neutral"}>
          {requested && blocked ? "در انتظار آماده‌سازی" : service.enabled ? "فعال" : "متوقف"}
        </Badge>
      </div>
    </CardHeader>
    <CardContent className="flex flex-1 flex-col gap-3 text-sm">
      <p className="leading-7 text-muted-foreground">{item.note}</p>
      {requested && service.blocked_reason ? <p className="rounded-md border p-2 text-xs leading-6">
        {prerequisiteMessages[service.blocked_reason] ?? "پیش‌نیاز سرویس را بررسی کنید."}
      </p> : null}
      <div className="mt-auto flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={() => setChoice(next)}>{labels[next]}</Button>
        <Button asChild size="sm" variant="ghost"><Link href={item.href}>تنظیمات مرتبط</Link></Button>
        {service.override !== null ? <Button type="button" size="sm" variant="ghost"
          onClick={() => setChoice("default")}>{labels.default}</Button> : null}
      </div>
      <Dialog open={choice !== null} label="تأیید تغییر سرویس" onClose={() => setChoice(null)}>
        {choice !== null ? <form action={changeService} className="space-y-4 p-5">
          <h2 className="text-lg font-semibold">{labels[choice]} «{item.title}»</h2>
          <p className="text-sm leading-7">
            {choice === "disable" ? "کارهای جدید این سرویس متوقف می‌شوند. کارهای در حال اجرا ممکن است تکمیل شوند."
              : choice === "default" ? "این سرویس دوباره از وضعیت پیش‌فرض نصب پیروی می‌کند."
                : blocked ? "درخواست فعال‌سازی ذخیره می‌شود. پس از آماده‌شدن پیش‌نیاز، سرویس می‌تواند کارهای تأییدشده را اجرا کند."
                  : "سرویس می‌تواند کارهای قبلاً تأییدشده را از صف اجرا کند."}
          </p>
          <input type="hidden" name="key" value={service.key} />
          <input type="hidden" name="choice" value={choice} />
          <input type="hidden" name="version" value={service.version} />
          <ConfirmButtons choice={choice} close={() => setChoice(null)} />
        </form> : null}
      </Dialog>
    </CardContent>
  </Card>;
}
