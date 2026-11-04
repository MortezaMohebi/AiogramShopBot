import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import {
  ConnectionControlPanel, type ConnectionData,
} from "@/components/blocks/connection-control-panel";
import { TelegramTransportPanel, type TelegramTransportData } from "@/components/blocks/telegram-transport-panel";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Params = Promise<{ saved?: string; verified?: string; error?: string }>;
const problems: Record<string, string> = {
  validation: "اطلاعات فرم معتبر نیست؛ فیلدها را بررسی کنید.",
  reauth: "برای اعمال تغییرات، ابتدا در حساب من هویت خود را مجدداً تأیید کنید.",
  identity: "هویت بات با Provider فعلی مغایرت دارد یا Credential معتبر نیست؛ هیچ توکنی تغییر نکرد.",
  probe: "تأیید هویت بات انجام نشد؛ API و اتصال شبکه را بررسی کنید.",
  save: "ذخیرهٔ تنظیمات انجام نشد؛ وضعیت سرویس را بررسی کنید.",
};

/** Show metadata, receiver health and explicit mode-change workflows together. */
export default async function BotConnectionsPage({
  searchParams,
}: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const [operations, telegramTransport, params] = await Promise.all([
    adminFetch<ConnectionData>("/connection-changes"),
    adminFetch<TelegramTransportData>("/telegram-transport"),
    searchParams,
  ]);
  return <div className="space-y-6">
    <PageHeading title="اتصال و مدیریت ربات‌ها" description="هویت پایدار، سلامت دریافت و پردازش، Maintenance Mode، Webhook و getUpdates دو پیام‌رسان." />
    {params.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">تنظیمات بات ثبت شد.</p> : null}
    {params.verified ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">شناسهٔ Provider با getMe تأیید شد.</p> : null}
    {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{problems[params.error] ?? "درخواست انجام نشد."}</p> : null}
    <p className="rounded-lg border bg-muted/30 p-4 text-sm">تنظیمات هر بات، روشن/خاموش‌کردن و تأیید هویت اکنون در <Link className="font-semibold underline" href="/bots">مدیریت ربات‌ها</Link> قرار دارند. این صفحه فقط زیرساخت اتصال و مسیرهای API را کنترل می‌کند.</p>
    <TelegramTransportPanel initial={telegramTransport} />
    <ConnectionControlPanel initial={operations} />
  </div>;
}
