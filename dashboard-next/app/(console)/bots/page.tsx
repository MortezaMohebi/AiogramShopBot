import Link from "next/link";
import { notFound } from "next/navigation";
import { Bot, Plus, ShieldCheck } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import {
  type BotRegistrySnapshot, botPlatformLabel, botRuntimeLabel,
} from "@/lib/bot-registry";
import { createBot, createStore } from "@/app/(console)/bots/actions";

type Params = Promise<{
  page?: string; platform?: string; store_id?: string;
  saved?: string; error?: string;
}>;

const problems: Record<string, string> = {
  validation: "اطلاعات فرم معتبر نیست؛ نام و شناسه‌ها را بررسی کنید.",
  reauth: "برای ساخت بات یا فروشگاه، در حساب من احراز هویت مجدد انجام دهید.",
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
  const platform = ["telegram", "bale"].includes(query.platform ?? "")
    ? query.platform! : "";
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
    <PageHeading title="مدیریت ربات‌ها" description="چندین ربات تلگرام و بله برای یک فروشگاه؛ هویت، دسترسی و وضعیت عملیاتی مستقل." />
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-muted/30 p-4 text-sm">
      <p className="max-w-3xl leading-7">دو بات قبلی همچنان از Runtime قدیمی استفاده می‌کنند. بات تازه در وضعیت Draft ایجاد می‌شود و تا تکمیل Runtime چندباتی، Webhook یا Polling خودکار فعال نخواهد داشت.</p>
      <Button asChild variant="outline"><Link href="/bot-connections">زیرساخت Webhook و Worker</Link></Button>
    </div>
    <div className="flex items-center gap-2 text-sm">
      <ShieldCheck className="size-4 text-primary" />
      <span>ساخت، تأیید Token و تغییر وضعیت بات به احراز هویت مجدد مدیر نیاز دارد.</span>
      <Button asChild variant="outline" size="sm"><Link href="/account">تأیید هویت</Link></Button>
    </div>
    {query.saved ? <p role="status" className="rounded-lg border bg-muted p-3 text-sm">ثبت اطلاعات انجام شد.</p> : null}
    {query.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">{problems[query.error] ?? problems.save}</p> : null}

    <Card><CardHeader><CardTitle className="flex items-center gap-2"><Bot className="size-5" /> فهرست بات‌ها</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <form method="get" className="flex flex-wrap items-end gap-3">
          <label className="space-y-2 text-sm">پیام‌رسان
            <select name="platform" defaultValue={platform} className="block h-10 min-w-36 rounded-md border bg-background px-3">
              <option value="">همه</option><option value="telegram">تلگرام</option><option value="bale">بله</option>
            </select>
          </label>
          <label className="space-y-2 text-sm">فروشگاه
            <select name="store_id" defaultValue={store_id} className="block h-10 min-w-48 rounded-md border bg-background px-3">
              <option value="">همهٔ فروشگاه‌ها</option>
              {result.stores.map(store => <option value={store.id} key={store.id}>{store.name}</option>)}
            </select>
          </label>
          <Button type="submit" variant="outline">فیلتر</Button>
          <Button asChild variant="outline"><Link href="/bots">پاک‌کردن</Link></Button>
        </form>
        <p className="text-xs text-muted-foreground">{result.total_bots.toLocaleString("fa-IR")} بات ثبت‌شده</p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">نام بات</th><th className="p-3">پیام‌رسان</th>
              <th className="p-3">وضعیت عملیاتی</th><th className="p-3">هویت تأییدشده</th>
              <th className="p-3">تنظیمات</th>
            </tr></thead>
            <tbody>{result.bots.map(bot => <tr key={bot.id} className="border-b align-top">
              <td className="p-3"><strong>{bot.name}</strong><p dir="ltr" className="text-xs text-muted-foreground">{bot.slug}</p></td>
              <td className="p-3">{botPlatformLabel(bot.platform)}</td>
              <td className="p-3"><Badge tone={bot.runtime_owner === "legacy" && bot.operations.desired_state === "active" ? "success" : "neutral"}>{botRuntimeLabel(bot)}</Badge></td>
              <td className="p-3 text-xs">{bot.provider_bot_id ?? "هنوز تأیید نشده"}</td>
              <td className="p-3"><Button asChild variant="outline" size="sm"><Link href={`/bots/${bot.id}`}>مدیریت بات</Link></Button></td>
            </tr>)}</tbody>
          </table>
          {!result.bots.length ? <p className="py-8 text-center text-sm text-muted-foreground">باتی مطابق فیلتر پیدا نشد.</p> : null}
        </div>
        <nav className="flex justify-between gap-3 text-sm" aria-label="صفحه‌بندی بات‌ها">
          {page > 1 ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page - 1)}>قبلی</Link></Button> : <span />}
          <span>صفحه {page.toLocaleString("fa-IR")} از {pages.toLocaleString("fa-IR")}</span>
          {page < pages ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page + 1)}>بعدی</Link></Button> : <span />}
        </nav>
      </CardContent>
    </Card>

    <div className="grid gap-5 lg:grid-cols-2">
      <Card><CardHeader><CardTitle><Plus className="me-2 inline size-5" /> ثبت بات جدید</CardTitle></CardHeader><CardContent>
        <form action={createBot} className="space-y-4">
          <label className="block space-y-2 text-sm">فروشگاه
            <select name="store_id" defaultValue={result.default_store_id} required className="h-10 w-full rounded-md border bg-background px-3">
              {result.stores.map(store => <option key={store.id} value={store.id}>{store.name} ({store.state})</option>)}
            </select>
          </label>
          <label className="block space-y-2 text-sm">نام بات
            <Input name="name" maxLength={160} required placeholder="مثلاً بات فروش محصولات صنعتی" />
          </label>
          <label className="block space-y-2 text-sm">شناسهٔ داخلی (Slug)
            <Input name="slug" dir="ltr" pattern="[a-z][a-z0-9-]{2,63}" minLength={3} maxLength={64} required placeholder="industrial-telegram" />
          </label>
          <label className="block space-y-2 text-sm">نوع پیام‌رسان
            <select name="platform" className="h-10 w-full rounded-md border bg-background px-3">
              <option value="telegram">Telegram</option><option value="bale">Bale</option>
            </select>
          </label>
          <p className="text-xs text-muted-foreground">ساخت بات هیچ پیام یا درخواست Provider ارسال نمی‌کند و Receiver را راه‌اندازی نمی‌کند.</p>
          <Button type="submit">ایجاد بات Draft</Button>
        </form>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>تعریف فروشگاه جدید</CardTitle></CardHeader><CardContent>
        <form action={createStore} className="space-y-4">
          <label className="block space-y-2 text-sm">نام فروشگاه
            <Input name="name" required maxLength={160} placeholder="نام نمایشی فروشگاه" />
          </label>
          <label className="block space-y-2 text-sm">شناسهٔ فروشگاه
            <Input name="slug" dir="ltr" required pattern="[a-z][a-z0-9-]{2,63}" placeholder="second-store" />
          </label>
          <p className="text-xs leading-7 text-muted-foreground">فروشگاه جدید در وضعیت Paused ساخته می‌شود. اتصال کاتالوگ، فروش و پرداخت مستقل پس از فاز Runtime انجام می‌شود.</p>
          <Button type="submit" variant="outline">ساخت فروشگاه غیرفعال</Button>
        </form>
      </CardContent></Card>
    </div>
  </div>;
}
