import { notFound } from "next/navigation";
import { BotConnectionsPanel } from "@/components/blocks/bot-connections-panel";
import { PageHeading } from "@/components/blocks/page-heading";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { BotConnections } from "@/lib/bot-connections";

/** Authenticated connection operations; never render a Bot API secret. */
export default async function BotConnectionsPage() {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const status = await adminFetch<BotConnections>("/bot-connections");

  return (
    <div className="space-y-6">
      <PageHeading
        title="اتصال ربات‌ها و Webhook"
        description="مدیریت روش دریافت پیام تلگرام و بله، تشخیص ارتباط واقعی و درخواست تغییر کنترل‌شدهٔ getUpdates/Webhook."
      />
      <BotConnectionsPanel initial={status} />
    </div>
  );
}
