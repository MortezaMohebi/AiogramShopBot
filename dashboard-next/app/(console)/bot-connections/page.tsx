import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { ConnectionControlPanel, type ConnectionData } from "@/components/blocks/connection-control-panel";
import { adminFetch, currentStaff } from "@/lib/bridge";
/** The private panel distinguishes requested configuration from verified state. */
export default async function BotConnectionsPage() {
  const staff = await currentStaff(); if (staff.role !== "superadmin") notFound();
  const operations = await adminFetch<ConnectionData>("/connection-changes");
  return <div className="space-y-6"><PageHeading title="اتصال ربات‌ها و اعمال تغییرات" description="مدیریت Webhook و getUpdates تلگرام و بله با تأیید هویت، تاریخچه و نتیجهٔ قابل پیگیری." /><ConnectionControlPanel initial={operations} /></div>;
}
