import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreCustomerList } from "@/lib/store-commerce";

type Query = Promise<{ page?: string }>;

export default async function StoreCustomersPage({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const query = await searchParams;
  const page = Math.max(1, Math.min(100000,
    Number.parseInt(query.page ?? "1", 10) || 1));
  const data = await adminFetch<StoreCustomerList>(
    `/store-customers?page=${page}&page_size=30`,
  );
  const pages = Math.max(1, Math.ceil(data.total / data.page_size));

  return <div className="space-y-6">
    <PageHeading title="مشتریان فروشگاه"
      description="هر پرونده می‌تواند چند حساب پیام‌رسان تأییدشده داشته باشد. شناسهٔ یکسان، مالکیت مشترک را ثابت نمی‌کند." />
    <div className="flex flex-wrap gap-2">
      <Button asChild size="sm" variant="outline">
        <Link href="/data-models/customers">جست‌وجوی پیشرفته و ورود و خروج مشتریان</Link>
      </Button>
    </div>
    <Card>
      <CardHeader><CardTitle>پرونده‌های مستقل مشتریان ({data.total})</CardTitle></CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">مشتری</th><th className="p-3">فروشگاه</th>
              <th className="p-3">هویت‌های تأییدشده</th>
            </tr></thead>
            <tbody>{data.items.map(row => <RecordClickArea as="tr" key={row.id} className="border-b">
              <td className="p-3"><RecordLink href={`/store-customers/${row.id}`}>#{row.id} · {row.display_name || "نام ثبت نشده"}</RecordLink></td>
              <td className="p-3 text-xs" dir="ltr">{row.store_id}</td>
              <td className="p-3">
                {row.identities.map(identity =>
                  <p key={identity.id} className="text-xs">
                    {identity.platform === "bale" ? "بله" : "تلگرام"} · ربات <bdi dir="ltr">{identity.bot_id.slice(0, 8)}</bdi> · <bdi dir="ltr">{identity.platform_user_id}</bdi>
                  </p>)}
              </td>
            </RecordClickArea>)}</tbody>
          </table>
        </div>
        {!data.items.length ? <p className="text-sm text-muted-foreground">
          هنوز مشتری‌ای ثبت نشده است.
        </p> : null}
        <div className="flex items-center justify-between text-sm">
          <span>صفحهٔ {page} از {pages}</span>
          <div className="flex gap-2">
            {page > 1 ? <Button asChild variant="outline" size="sm">
              <Link href={`/store-customers?page=${page - 1}`}>قبلی</Link>
            </Button> : null}
            {page < pages ? <Button asChild variant="outline" size="sm">
              <Link href={`/store-customers?page=${page + 1}`}>بعدی</Link>
            </Button> : null}
          </div>
        </div>
      </CardContent>
    </Card>
  </div>;
}
