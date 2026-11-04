import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminFetch, currentStaff } from "@/lib/bridge";

interface Count {
  store_id: string;
  status: string;
  count: number;
}

interface NotificationReport {
  stock_alerts: Count[];
  delivery_outbox: Count[];
  unknown_delivery_requires_review: boolean;
}

/** Read-only delivery telemetry; uncertain sends are never blindly replayed. */
export default async function CustomerNotificationsPage() {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const status = await adminFetch<NotificationReport>("/customer-notifications");
  return <div className="space-y-5">
    <PageHeading title="اعلان‌های مشتری و موجودی"
      description="اشتراک موجودی برای هر Bot جداست؛ ارسال نامشخص نیازمند بررسی است و به‌صورت خودکار تکرار نمی‌شود." />
    <div className="grid gap-4 lg:grid-cols-2">
      {([
        ["Subscriptionهای موجودی", status.stock_alerts],
        ["Outbox عملیاتی", status.delivery_outbox],
      ] as const).map(([title, items]) => <Card key={title}>
        <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {items.map(item => <div key={item.store_id + item.status}
            className="flex flex-wrap justify-between gap-3 border-b p-2 text-sm">
            <span>{item.store_id.slice(0, 8)} · {item.status}</span>
            <strong>{item.count}</strong>
          </div>)}
          {!items.length ? <p className="text-sm text-muted-foreground">رکوردی ثبت نشده است.</p> : null}
        </CardContent>
      </Card>)}
    </div>
    <p className="text-sm leading-7 text-muted-foreground">
      این بخش آمار صف را نشان می‌دهد، نه تأیید دریافت اعلان در Telegram یا Bale.
      پیاده‌سازی Dispatch Worker و آزمایش واقعی Provider شرط فعال‌سازی است.
    </p>
  </div>;
}
