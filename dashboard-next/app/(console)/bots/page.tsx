import { ListSearch } from "@/components/blocks/search-tools";
import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { notFound } from "next/navigation";
import { Bot, Plus } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import {
  type BotRegistrySnapshot, botPlatformLabel, botRuntimeLabel,
} from "@/lib/bot-registry";
import { createBot } from "@/app/(console)/bots/actions";

type Params = Promise<{
  page?: string; platform?: string; store_id?: string;
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
    <PageHeading title="مدیریت ربات‌ها" />
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/30 p-4 text-sm">
      <p className="max-w-3xl leading-7">ربات جدید ابتدا به‌صورت پیش‌نویس ایجاد می‌شود. برای شروع کار، Token را تأیید و دریافت پیام را فعال کنید.</p>
    </div>
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">ثبت اطلاعات انجام شد.</p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{problems[query.error] ?? problems.save}</p> : null}

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Bot className="size-5" /> فهرست ربات‌ها</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <ListSearch path="/bots" values={{
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
        <p className="text-xs text-muted-foreground">{result.total_bots.toLocaleString("fa-IR")} ربات ثبت‌شده</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[550px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نام ربات</th><th className="p-3">پیام‌رسان</th>
              <th className="p-3">وضعیت عملیاتی</th><th className="p-3">هویت تأییدشده</th>
            </tr></thead>
            <tbody>{result.bots.map(bot => <RecordClickArea as="tr" key={bot.id} className="border-b align-top">
              <td className="p-3"><RecordLink href={`/bots/${bot.id}`}>{bot.name}</RecordLink><p dir="ltr" className="text-xs text-muted-foreground">{bot.slug}</p></td>
              <td className="p-3">{botPlatformLabel(bot.platform)}</td>
              <td className="p-3"><Badge tone={bot.operations.desired_state === "active" && bot.operations.runtime_ready ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge></td>
              <td className="p-3 text-xs">{bot.provider_bot_id ?? "هنوز تأیید نشده"}</td>
            </RecordClickArea>)}</tbody>
          </table>
          {!result.bots.length ? <p className="py-8 text-center text-sm text-muted-foreground">{platform || store_id ? "رباتی با این فیلترها پیدا نشد." : "هنوز رباتی ثبت نشده است. از فرم زیر ربات ایجاد کنید."}</p> : null}
        </div>
        <nav className="flex justify-between gap-3 text-sm" aria-label="صفحه‌بندی ربات‌ها">
          {page > 1 ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page - 1)}>قبلی</Link></Button> : <span />}
          <span>صفحه {page.toLocaleString("fa-IR")} از {pages.toLocaleString("fa-IR")}</span>
          {page < pages ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page + 1)}>بعدی</Link></Button> : <span />}
        </nav>
      </CardContent>
    </Card>

    <Card><CardHeader><CardTitle><Plus aria-hidden="true" className="me-2 inline size-5" /> ثبت ربات جدید</CardTitle></CardHeader><CardContent>
      <form action={createBot} className="space-y-4">
        <label className="block space-y-2 text-sm">فروشگاه
          <select name="store_id" defaultValue={result.default_store_id} required className="h-10 w-full rounded-md border bg-background px-3">
            {result.stores.map(store => <option key={store.id} value={store.id}>{store.name} ({({ active: "فعال", paused: "متوقف", disabled: "غیرفعال", draft: "پیش‌نویس", archived: "بایگانی‌شده" } as Record<string, string>)[store.state] ?? store.state})</option>)}
          </select>
        </label>
        <label className="block space-y-2 text-sm">نام ربات
          <Input name="name" maxLength={160} required placeholder="مثلاً ربات فروش محصولات صنعتی" />
        </label>
        <label className="block space-y-2 text-sm">شناسهٔ داخلی (Slug، اختیاری)
          <Input name="slug" dir="ltr" pattern="[a-z][a-z0-9\-]{2,63}" minLength={3} maxLength={64}
            aria-describedby="bot-slug-hint" placeholder="industrial-telegram" />
        </label>
        <p id="bot-slug-hint" className="text-xs text-muted-foreground">اگر خالی بماند، شناسه به‌صورت خودکار ساخته می‌شود.</p>
        <label className="block space-y-2 text-sm">نوع پیام‌رسان
          <select name="platform" className="h-10 w-full rounded-md border bg-background px-3">
            <option value="telegram">تلگرام</option><option value="bale">بله</option>
          </select>
        </label>
        <p className="text-xs text-muted-foreground">ایجاد پیش‌نویس، ربات را فعال نمی‌کند.</p>
        <Button type="submit">ایجاد ربات پیش‌نویس</Button>
      </form>
    </CardContent></Card>
  </div>;
}
