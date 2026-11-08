import Link from "next/link";
import { RecordClickArea } from "@/components/ui/record-click-area";
import { RecordLink } from "@/components/ui/record-link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { SupportTicketSummary } from "@/lib/customer-experience";

type Query = Promise<{ status?: string }>;
const STATUSES = ["all", "open", "pending", "resolved", "closed"];
const STATUS_LABELS: Record<string, string> = {
  all: "همه", open: "باز", pending: "در انتظار", resolved: "حل‌شده", closed: "بسته‌شده",
};

/** A Staff member sees only active, authorized Store tickets. */
export default async function SupportTickets({
  searchParams,
}: { searchParams: Query }) {
  const query = await searchParams;
  const status = STATUSES.includes(query.status ?? "")
    ? query.status ?? "all" : "all";
  const params = status === "all" ? "" : `?status=${status}`;
  const results = await adminFetch<{ items: SupportTicketSummary[] }>(
    `/support-tickets${params}`,
  );
  return <div className="space-y-5">
    <PageHeading title="مرکز پشتیبانی مشتریان"
      />
    <nav className="flex flex-wrap gap-2" aria-label="فیلتر وضعیت درخواست‌ها">
      {STATUSES.map(item => <Button key={item} asChild
        variant={item === status ? "secondary" : "outline"} size="sm">
        <Link href={item === "all" ? "/support-tickets" : `/support-tickets?status=${item}`}
          aria-current={item === status ? "page" : undefined}>
          {STATUS_LABELS[item]}
        </Link>
      </Button>)}
    </nav>
    <Card>
      <CardHeader><CardTitle>درخواست‌های مشتریان ({results.items.length})</CardTitle></CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[530px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">شناسه</th>
              <th className="p-3">مشتری</th>
              <th className="p-3">موضوع</th>
              <th className="p-3">فروشگاه / ربات</th>
              <th className="p-3">وضعیت</th>
            </tr></thead>
            <tbody>{results.items.map(ticket => <RecordClickArea as="tr" key={ticket.id} className="border-b">
              <td className="p-3"><RecordLink href={`/support-tickets/${ticket.id}`}>#{ticket.id}</RecordLink></td>
              <td className="p-3">#{ticket.customer_id}</td>
              <td className="p-3">{ticket.topic}</td>
              <td className="p-3 text-xs" dir="ltr">
                {ticket.store_id.slice(0, 8)} / {ticket.bot_id.slice(0, 8)}
              </td>
              <td className="p-3">{STATUS_LABELS[ticket.status] ?? ticket.status}</td>
            </RecordClickArea>)}</tbody>
          </table>
        </div>
        {!results.items.length ? <p className="p-4 text-sm text-muted-foreground">
          در این وضعیت درخواست پشتیبانی وجود ندارد.
        </p> : null}
      </CardContent>
    </Card>
  </div>;
}
