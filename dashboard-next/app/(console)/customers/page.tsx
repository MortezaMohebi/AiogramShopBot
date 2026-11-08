import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { adminFetch } from "@/lib/bridge";
import type { Paginated } from "@/lib/types";

interface CustomerRow {
  id: number;
  platform: "telegram" | "bale";
  user_id: string;
  username: string | null;
  name: string | null;
  is_blocked: boolean;
  allow_announcements: boolean;
  restriction_until: string | null;
  bot_blocked_by_customer: boolean | null;
  tags: string[];
  support_status: string;
  owner_staff_id: number | null;
}
type Params = Promise<{
  page?: string; q?: string; platform?: string;
  restriction?: string; consent?: string; tag?: string; owner?: string;
}>;
const platforms = new Set(["all", "telegram", "bale"]);
const restrictions = new Set(["all", "blocked", "active"]);
const consents = new Set(["all", "yes", "no"]);

/** Customers always keep platform-bound IDs and consent provenance separately. */
export default async function CustomersPage({
  searchParams,
}: { searchParams: Params }) {
  const params = await searchParams;
  const page = Math.min(100000, Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1));
  const filters = new URLSearchParams({ page: String(page) });
  const q = (params.q ?? "").trim().slice(0, 100);
  const tag = (params.tag ?? "").trim().slice(0, 32);
  const platform = platforms.has(params.platform ?? "") ? params.platform! : "all";
  const restriction = restrictions.has(params.restriction ?? "") ? params.restriction! : "all";
  const consent = consents.has(params.consent ?? "") ? params.consent! : "all";
  if (q) filters.set("q", q);
  if (tag) filters.set("tag", tag);
  filters.set("platform", platform);
  filters.set("restriction", restriction);
  filters.set("consent", consent);
  if (params.owner && /^[1-9][0-9]*$/.test(params.owner)) filters.set("owner", params.owner);
  const hasFilters = Boolean(q || tag || filters.has("owner") ||
    platform !== "all" || restriction !== "all" || consent !== "all");

  const [result, operators] = await Promise.all([
    adminFetch<Paginated<CustomerRow>>(`/customers?${filters}`),
    adminFetch<{ items: { id: number; username: string }[] }>("/customers/assignees"),
  ]);
  const usernames = new Map(operators.items.map((item) => [item.id, item.username]));
  const maxPages = Math.max(1, Math.ceil(result.total / result.page_size));
  function pageUrl(target: number) {
    const next = new URLSearchParams(filters);
    next.set("page", String(target));
    return `/customers?${next}`;
  }

  return <div className="space-y-5">
    <PageHeading title="مدیریت مشتریان" />
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <Link href="/data-models/customers">جست‌وجوی پیشرفته و ورود و خروج مشتریان</Link>
      </Button>
    </div>
    <Card><CardContent className="pt-5">
      <form method="get" className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <label className="space-y-2 text-sm xl:col-span-2">نام، نام کاربری یا شناسه
          <Input name="q" maxLength={100} defaultValue={q} placeholder="جست‌وجوی مشتری…" />
        </label>
        <label className="space-y-2 text-sm">پیام‌رسان
          <select name="platform" defaultValue={platform} className="h-10 w-full rounded-md border bg-background px-2">
            <option value="all">همه</option><option value="telegram">تلگرام</option><option value="bale">بله</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">وضعیت محدودسازی
          <select name="restriction" defaultValue={restriction} className="h-10 w-full rounded-md border bg-background px-2">
            <option value="all">همه</option><option value="blocked">مسدود</option><option value="active">فعال</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">رضایت تبلیغاتی
          <select name="consent" defaultValue={consent} className="h-10 w-full rounded-md border bg-background px-2">
            <option value="all">همه</option><option value="yes">دارد</option><option value="no">ندارد</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">برچسب
          <Input name="tag" maxLength={32} defaultValue={tag} placeholder="مثلاً عمده‌فروش" />
        </label>
        <label className="space-y-2 text-sm md:col-span-2">مسئول پیگیری
          <select name="owner" defaultValue={params.owner ?? ""} className="h-10 w-full rounded-md border bg-background px-2">
            <option value="">همه</option>
            {operators.items.map((item) => <option key={item.id} value={item.id}>{item.username}</option>)}
          </select>
        </label>
        <div className="flex items-end gap-2">
          <Button type="submit">جست‌وجو و فیلتر</Button>
          <Button asChild type="button" variant="outline"><Link href="/customers">پاک‌کردن</Link></Button>
        </div>
      </form>
    </CardContent></Card>
    <Card><CardContent className="overflow-x-auto pt-5">
      <p className="mb-3 text-xs text-muted-foreground">{result.total.toLocaleString("fa-IR")} مشتری مطابق جست‌وجو</p>
      <table className="w-full min-w-[580px] text-right text-sm">
        <thead><tr className="border-b text-muted-foreground">
          <th className="p-3">نام و شناسه</th><th className="p-3">پیام‌رسان</th>
          <th className="p-3">وضعیت فروشگاه</th><th className="p-3">رضایت تبلیغاتی</th>
          <th className="p-3">مسئول و برچسب</th>
        </tr></thead>
        <tbody>{result.items.map((customer) => <RecordClickArea as="tr" key={customer.id} className="border-b align-top">
          <td className="p-3">
            <RecordLink href={`/customers/${customer.id}`}>
              {customer.name || (customer.username ? <bdi>@{customer.username}</bdi> : <>مشتری <bdi>{customer.user_id}</bdi></>)}
            </RecordLink>
            {customer.name || customer.username ? <p dir="ltr" className="text-xs text-muted-foreground">
              {customer.name && customer.username ? `@${customer.username}` : customer.user_id}
            </p> : null}
          </td>
          <td className="p-3">{customer.platform === "telegram" ? "تلگرام" : "بله"}</td>
          <td className="p-3"><Badge tone={customer.is_blocked ? "danger" : "neutral"}>{customer.is_blocked ? "محدود" : "فعال"}</Badge>
            <p className="mt-1 text-xs text-muted-foreground">مسدودکردن ربات توسط مشتری: {customer.bot_blocked_by_customer === null ? "نامشخص" : customer.bot_blocked_by_customer ? "تأییدشده" : "ثبت‌نشده"}</p>
          </td>
          <td className="p-3"><Badge tone={customer.allow_announcements ? "success" : "neutral"}>{customer.allow_announcements ? "دارای رضایت" : "بدون رضایت"}</Badge></td>
          <td className="p-3"><p className="text-xs">{customer.owner_staff_id ? usernames.get(customer.owner_staff_id) ?? "—" : "بدون مسئول"}</p>
            <p className="mt-1 max-w-48 break-words text-xs text-muted-foreground">{customer.tags.join("، ") || "بدون برچسب"}</p>
          </td>
        </RecordClickArea>)}</tbody>
      </table>
      {!result.items.length ? <p className="py-9 text-center text-sm text-muted-foreground">{hasFilters
        ? "مشتری‌ای با این فیلترها پیدا نشد. فیلترها را تغییر دهید یا پاک کنید."
        : "هنوز مشتری‌ای ثبت نشده است."}</p> : null}
      <nav className="mt-5 flex flex-wrap items-center justify-between gap-2 text-sm" aria-label="صفحه‌بندی مشتریان">
        {page > 1 ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page - 1)}>قبلی</Link></Button> : <span />}
        <span>صفحه {page.toLocaleString("fa-IR")} از {maxPages.toLocaleString("fa-IR")}</span>
        {page < maxPages ? <Button asChild variant="outline" size="sm"><Link href={pageUrl(page + 1)}>بعدی</Link></Button> : <span />}
      </nav>
    </CardContent></Card>
  </div>;
}
