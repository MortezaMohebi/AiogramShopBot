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
  identity: "شناسهٔ ربات مطابقت ندارد یا Token معتبر نیست؛ Token تغییر نکرد.",
  probe: "تأیید هویت ربات انجام نشد؛ API و اتصال شبکه را بررسی کنید.",
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
    <PageHeading title="تنظیمات اتصال ربات‌ها" />
    {params.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">تنظیمات ربات ثبت شد.</p> : null}
    {params.verified ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">شناسهٔ ربات با getMe تأیید شد.</p> : null}
    {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{problems[params.error] ?? "درخواست انجام نشد."}</p> : null}
    <p className="rounded-lg border bg-muted/30 p-4 text-sm">برای ویرایش مشخصات، تغییر وضعیت و تأیید هویت هر ربات به <Link className="font-semibold underline" href="/bots">مدیریت ربات‌ها</Link> بروید.</p>
    <TelegramTransportPanel initial={telegramTransport} />
    <ConnectionControlPanel initial={operations} />
  </div>;
}
