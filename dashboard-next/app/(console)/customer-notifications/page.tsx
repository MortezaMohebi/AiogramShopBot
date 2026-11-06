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
const STATUS_LABELS: Record<string, string> = {
  active: "فعال", queued: "در صف", processing: "در حال پردازش",
  notified: "اطلاع‌رسانی‌شده", sent: "ارسال‌شده",
  needs_review: "نیازمند بررسی", cancelled: "لغوشده",
};

/** Read-only delivery telemetry; uncertain sends are never blindly replayed. */
export default async function CustomerNotificationsPage() {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const status = await adminFetch<NotificationReport>("/customer-notifications");
  return <div className="space-y-5">
    <PageHeading title="اعلان‌های مشتری و موجودی"
      description="اعلان موجودی برای هر ربات جداست. ارسال نامشخص نیازمند بررسی است و خودکار تکرار نمی‌شود." />
    <div className="grid gap-4 lg:grid-cols-2">
      {([
        ["درخواست‌های اطلاع از موجودی", status.stock_alerts],
        ["صف اعلان‌ها", status.delivery_outbox],
      ] as const).map(([title, items]) => <Card key={title}>
        <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {items.map(item => <div key={item.store_id + item.status}
            className="flex flex-wrap justify-between gap-3 border-b p-2 text-sm">
            <span>فروشگاه <bdi dir="ltr">{item.store_id.slice(0, 8)}</bdi> · {STATUS_LABELS[item.status] ?? item.status}</span>
            <strong>{item.count}</strong>
          </div>)}
          {!items.length ? <p className="text-sm text-muted-foreground">رکوردی ثبت نشده است.</p> : null}
        </CardContent>
      </Card>)}
    </div>
    <p className="text-sm leading-7 text-muted-foreground">
      این آمار، وضعیت صف اعلان‌ها را نشان می‌دهد و تأیید دریافت پیام در تلگرام یا بله نیست.
    </p>
  </div>;
}
