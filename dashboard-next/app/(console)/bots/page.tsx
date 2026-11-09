import { ListSearch } from "@/components/blocks/search-tools";
import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { notFound } from "next/navigation";
import { Plus } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { adminFetch, currentStaff } from "@/lib/bridge";
import {
  type BotRegistrySnapshot, botPlatformLabel, botRuntimeLabel,
} from "@/lib/bot-registry";
import { ListRangePager } from "@/components/blocks/list-range-pager";

type Params = Promise<{
  page?: string; platform?: string; store_id?: string; search?: string;
  saved?: string; error?: string;
}>;

const problems: Record<string, string> = {
  validation: "اطلاعات فرم معتبر نیست؛ نام و شناسه‌ها را بررسی کنید.",
  reauth: "برای ساخت ربات، هویت خود را در همین صفحه تأیید کنید.",
  conflict: "شناسهٔ انتخاب‌شده قبلاً ثبت شده یا نسخهٔ اطلاعات تغییر کرده است.",
  save: "ثبت انجام نشد؛ سرویس و دسترسی حساب را بررسی کنید.",
};

/** Registry lists all bots; it never confuses a draft with an active receiver. */
export default async function BotsPage({
  searchParams,
}: { searchParams: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(query.page ?? "1", 10) || 1));
  const filters = new URLSearchParams({
    page: String(page), page_size: "30",
  });
  const platform = query.platform === "telegram" || query.platform === "bale"
    ? query.platform : "";
  if (platform) filters.set("platform", platform);
  const store_id = /^[0-9a-f-]{36}$/i.test(query.store_id ?? "")
    ? query.store_id! : "";
  if (store_id) filters.set("store_id", store_id);
  const search = query.search?.trim().slice(0, 160) ?? "";
  if (search) filters.set("search", search);
  const result = await adminFetch<BotRegistrySnapshot>(
    `/bot-registry?${filters.toString()}`,
  );
  const pages = Math.max(1, Math.ceil(result.total_bots / result.page_size));

  function pageUrl(number: number): string {
    const values = new URLSearchParams(filters);
    values.set("page", String(number));
    return `/bots?${values.toString()}`;
  }

  return <div className="space-y-6">
    <PageHeading title="ربات‌ها" action={<Button asChild><Link href="/bots/new"><Plus /> ربات جدید</Link></Button>} />
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">ثبت اطلاعات انجام شد.</p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{problems[query.error] ?? problems.save}</p> : null}

    <Card><CardContent className="space-y-4 pt-5">
        <div className="grid items-end gap-3 lg:grid-cols-[1fr_auto]">
        <ListSearch path="/bots" query={{ name: "search", label: "جست‌وجوی ربات‌ها", value: search, placeholder: "نام یا نام کاربری ربات…" }} values={{
          platform: { label: "پیام‌رسان", value: platform, display: platform ? botPlatformLabel(platform) : "" },
          store_id: { label: "فروشگاه", value: store_id, display: result.stores.find(store => store.id === store_id)?.name },
        }} filters={<>
          <label className="space-y-2 text-sm">پیام‌رسان
            <select name="platform" defaultValue={platform} className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="">همه</option><option value="telegram">تلگرام</option><option value="bale">بله</option>
            </select>
          </label>
          <label className="space-y-2 text-sm">فروشگاه
            <select name="store_id" defaultValue={store_id} className="block h-10 w-full rounded-md border bg-background px-3">
              <option value="">همهٔ فروشگاه‌ها</option>
              {result.stores.map(store => <option value={store.id} key={store.id}>{store.name}</option>)}
            </select>
          </label>
        </>} />
        <ListRangePager start={result.bots.length ? (page - 1) * result.page_size + 1 : 0}
          end={result.bots.length ? (page - 1) * result.page_size + result.bots.length : 0} total={result.total_bots}
          previous={page > 1 ? pageUrl(page - 1) : undefined} next={page < pages ? pageUrl(page + 1) : undefined}
          label="صفحه‌بندی ربات‌ها" />
        </div>
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[29rem] text-right text-sm">
            <thead className="bg-muted"><tr className="border-b">
              <th className="p-3">نام ربات</th><th className="p-3">پیام‌رسان</th>
              <th className="p-3">وضعیت عملیاتی</th><th className="p-3">هویت تأییدشده</th>
            </tr></thead>
            <tbody>{result.bots.map(bot => <RecordClickArea as="tr" key={bot.id} className="border-b align-top">
              <td className="p-3"><RecordLink href={`/bots/${bot.id}`}>{bot.name}</RecordLink><p dir="ltr" className="text-xs text-muted-foreground">{bot.provider_username ? "@" + bot.provider_username : bot.slug}</p></td>
              <td className="p-3">{botPlatformLabel(bot.platform)}</td>
              <td className="p-3"><Badge tone={bot.operations.desired_state === "active" && bot.operations.runtime_ready ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge></td>
              <td className="p-3 text-xs">{bot.provider_bot_id ? "تأیید شده" : "تأیید نشده"}</td>
            </RecordClickArea>)}</tbody>
          </table>
          {!result.bots.length ? <p className="py-8 text-center text-sm text-muted-foreground">{platform || store_id || search ? "رباتی با این جست‌وجو پیدا نشد." : "هنوز رباتی ثبت نشده است."}</p> : null}
        </div>
      </CardContent>
    </Card>
  </div>;
}
