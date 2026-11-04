import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { adminFetch } from "@/lib/bridge";
import type { SupportTicketDetails } from "@/lib/customer-experience";
import { replyToTicket } from "../actions";

type Params = Promise<{ id: string }>;
type Query = Promise<{ saved?: string; error?: string }>;

/** Show Store-scoped support messages with one versioned staff reply form. */
export default async function TicketPage({
  params, searchParams,
}: { params: Params; searchParams: Query }) {
  const { id } = await params;
  if (!/^[1-9][0-9]{0,15}$/.test(id)) notFound();
  const [ticket, query] = await Promise.all([
    adminFetch<SupportTicketDetails>(`/support-tickets/${id}`),
    searchParams,
  ]);
  return <div className="space-y-5">
    <Button asChild variant="outline" size="sm">
      <Link href="/support-tickets">بازگشت به درخواست‌ها</Link>
    </Button>
    <PageHeading title={`تیکت #${ticket.id}`}
      description={`موضوع: ${ticket.topic} · وضعیت: ${ticket.status} · Store: ${ticket.store_id}`} />
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      پاسخ ذخیره شد. اطلاع‌رسانی مشتری از طریق Outbox مستقل انجام می‌شود.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      پاسخ ثبت نشد؛ وضعیت تیکت، Store جاری و مجوزها را بررسی کنید.
    </p> : null}
    <Card>
      <CardHeader><CardTitle>گفت‌وگو با مشتری #{ticket.customer_id}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {ticket.messages.map(item => <article key={item.id} className="space-y-2 rounded-lg border p-3 text-sm">
          <p className="font-semibold">
            {item.sender_kind === "customer" ? "مشتری" : item.sender_kind === "staff" ? "پشتیبان" : "سیستم"}
          </p>
          <p className="whitespace-pre-wrap break-words">{item.body}</p>
          <p className="text-xs text-muted-foreground" dir="ltr">{item.created_at}</p>
        </article>)}
        {!ticket.messages.length ? <p className="text-sm text-muted-foreground">هنوز پیامی ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
    {ticket.status !== "closed" ? <Card>
      <CardHeader><CardTitle>پاسخ به مشتری</CardTitle></CardHeader>
      <CardContent><form action={replyToTicket} className="space-y-4">
        <input type="hidden" name="ticket_id" value={ticket.id} />
        <input type="hidden" name="expected_version" value={ticket.version} />
        <label className="block space-y-2 text-sm">
          متن پاسخ
          <Textarea name="body" maxLength={4000} minLength={1}
            required rows={5} placeholder="پاسخ دقیق و قابل پیگیری برای مشتری..." />
        </label>
        <p className="text-xs leading-6 text-muted-foreground">
          پاسخ به تاریخچهٔ همین تیکت اضافه می‌شود و از طریق پیام‌رسان Bot
          مبدأ برای مشتری قابل پیگیری خواهد بود. ارسال پیام پس از Timeout
          به‌صورت خودکار تکرار نمی‌شود.
        </p>
        <Button type="submit">ثبت پاسخ</Button>
      </form></CardContent>
    </Card> : null}
  </div>;
}
