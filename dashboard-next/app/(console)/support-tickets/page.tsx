import Link from "next/link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { SupportTicketSummary } from "@/lib/customer-experience";

type Query = Promise<{ status?: string }>;
const STATUSES = ["all", "open", "pending", "resolved", "closed"];

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
      description="تیکت‌های Telegram/Bale با مالکیت Store و Customer؛ هیچ وضعیت پرداختی از این بخش تغییر نمی‌کند." />
    <nav className="flex flex-wrap gap-2">
      {STATUSES.map(item => <Button key={item} asChild
        variant={item === status ? "secondary" : "outline"} size="sm">
        <Link href={item === "all" ? "/support-tickets" : `/support-tickets?status=${item}`}>
          {item === "all" ? "همه" : item}
        </Link>
      </Button>)}
    </nav>
    <Card>
      <CardHeader><CardTitle>درخواست‌های مشتریان ({results.items.length})</CardTitle></CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[670px] text-right text-sm">
            <thead><tr className="border-b text-muted-foreground">
              <th className="p-3">شناسه</th>
              <th className="p-3">Customer</th>
              <th className="p-3">موضوع</th>
              <th className="p-3">Store / Bot</th>
              <th className="p-3">وضعیت</th>
              <th className="p-3">جزئیات</th>
            </tr></thead>
            <tbody>{results.items.map(ticket => <tr key={ticket.id} className="border-b">
              <td className="p-3">#{ticket.id}</td>
              <td className="p-3">#{ticket.customer_id}</td>
              <td className="p-3">{ticket.topic}</td>
              <td className="p-3 text-xs" dir="ltr">
                {ticket.store_id.slice(0, 8)} / {ticket.bot_id.slice(0, 8)}
              </td>
              <td className="p-3">{ticket.status}</td>
              <td className="p-3"><Button asChild variant="outline" size="sm">
                <Link href={`/support-tickets/${ticket.id}`}>مشاهده</Link>
              </Button></td>
            </tr>)}</tbody>
          </table>
        </div>
        {!results.items.length ? <p className="p-4 text-sm text-muted-foreground">
          در این وضعیت درخواست پشتیبانی وجود ندارد.
        </p> : null}
      </CardContent>
    </Card>
  </div>;
}
