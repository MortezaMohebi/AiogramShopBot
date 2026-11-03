import { notFound } from "next/navigation";
import Link from "next/link";
import { reviewOrder } from "@/app/(console)/orders/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { OrderTable } from "@/components/blocks/order-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr, statusLabel } from "@/lib/utils";
import type { Order, Paginated } from "@/lib/types";

type ReviewOrder = {
  id: number; platform: string; status: string; product_id: number;
  total_irr: string;
};
type Params = Promise<{page?: string; saved?: string; error?: string}>;

/** Only prepayment requests permit managerial decisions; never mark Paid. */
export default async function OrdersPage({ searchParams }: { searchParams: Params }) {
  const [params, staff] = await Promise.all([searchParams, currentStaff()]);
  if (!["superadmin", "sales", "finance"].includes(staff.role)) notFound();
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const [result, queue] = await Promise.all([
    adminFetch<Paginated<Order>>(`/orders?page=${page}`),
    ["superadmin", "sales"].includes(staff.role)
      ? adminFetch<ReviewOrder[]>("/orders/review-queue")
      : Promise.resolve([]),
  ]);
  const last = Math.max(1, Math.ceil(result.total / result.page_size));
  return (
    <div className="space-y-6">
      <PageHeading title="سفارش‌ها" description="سفارش‌های تلگرام و بله با وضعیت واقعی پرداخت؛ مدیر فقط درخواست‌های پیش از پرداخت را قبول یا رد می‌کند." />
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href="/data-models/orders">Search، Group By تاریخ و Export سفارش‌ها</Link>
        </Button>
      </div>
      {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تصمیم مدیر در سوابق سفارش ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">تصمیم انجام نشد. وضعیت سفارش، موجودی کالای منتشرشده و عبارت تأیید را بررسی کنید.</p> : null}
      {["superadmin", "sales"].includes(staff.role) ? (
        <Card>
          <CardHeader><CardTitle>درخواست‌های نیازمند بررسی دستی</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {queue.map((order) => (
              <div key={order.id} className="grid items-start gap-4 rounded-lg border border-border p-4 lg:grid-cols-[1fr_1.4fr]">
                <div className="space-y-2">
                  <p className="text-sm font-semibold">سفارش #{order.id} · {order.platform === "bale" ? "بله" : "تلگرام"}</p>
                  <p className="text-xs text-muted-foreground">محصول #{order.product_id} · {formatIrr(order.total_irr)}</p>
                  <Badge tone="warning">{statusLabel(order.status)}</Badge>
                </div>
                <div className="flex flex-col gap-3">
                  {order.status === "pending_review" ? (
                    <form action={reviewOrder} className="flex flex-wrap items-center gap-2">
                      <input type="hidden" name="order_id" value={order.id} />
                      <input type="hidden" name="decision" value="accept" />
                      <Input name="confirmation" placeholder="ACCEPT_UNPAID_ORDER" aria-label="تأیید سفارش بدون پرداخت" dir="ltr" required className="max-w-60 text-xs" />
                      <Button type="submit" size="sm">قبول درخواست (بدون ثبت پرداخت)</Button>
                    </form>
                  ) : null}
                  <form action={reviewOrder} className="flex flex-wrap items-center gap-2">
                    <input type="hidden" name="order_id" value={order.id} />
                    <input type="hidden" name="decision" value="reject" />
                    <Input name="confirmation" placeholder="REJECT_UNPAID_ORDER" aria-label="تأیید رد درخواست" dir="ltr" required className="max-w-60 text-xs" />
                    <Button type="submit" size="sm" variant="destructive">لغو درخواست</Button>
                  </form>
                </div>
              </div>
            ))}
            {!queue.length ? <p className="py-4 text-sm text-muted-foreground">سفارشی برای بررسی دستی موجود نیست.</p> : null}
            <p className="text-xs text-muted-foreground">قبول سفارش فقط وضعیت آن را «تأییدشده، بدون پرداخت» می‌کند؛ موجودی کم نمی‌شود و هیچ پرداختی تأیید نمی‌شود.</p>
          </CardContent>
        </Card>
      ) : null}
      <OrderTable title="فهرست سفارش‌های مشترک" orders={result.items} />
      <nav aria-label="صفحه‌بندی سفارش" className="flex items-center justify-end gap-3">
        <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${Math.max(1, page - 1)}`}>قبلی</Link></Button>
        <span className="text-sm tabular text-muted-foreground">صفحه {page} از {last}</span>
        <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${Math.min(last, page + 1)}`}>بعدی</Link></Button>
      </nav>
    </div>
  );
}
