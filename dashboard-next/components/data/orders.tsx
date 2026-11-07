import Link from "next/link";
import { reviewOrder } from "@/app/(console)/orders/actions";
import { OrderTable } from "@/components/blocks/order-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { readSection } from "@/lib/read-section";
import { statusLabel } from "@/lib/utils";
import { formatOrderAmount, type OrderAmount } from "@/lib/order-money";
import type { Order, Paginated } from "@/lib/types";
import { DataSectionError } from "./section-error";
export type ReviewOrder = OrderAmount & { id: number; platform: string; status: string; product_id: number; total_irr: string };

/** The list and review queue fetch independently after the page's role check. */
export async function OrdersResults({ page }: { page: number }) {
  const result = await readSection<Paginated<Order>>(`/orders?page=${page}`);
  if (!result.ok) return <DataSectionError title="سفارش‌ها دریافت نشدند" />;
  return <OrdersList data={result.data} page={page} />;
}
export async function ReviewQueue() {
  const result = await readSection<ReviewOrder[]>("/orders/review-queue");
  if (!result.ok) return <DataSectionError title="درخواست‌ها دریافت نشدند" />;
  return <ReviewQueueView queue={result.data} />;
}
/** Render only confirmed order-list data and its matching pagination. */
export function OrdersList({ data: result, page }: { data: Paginated<Order>; page: number }) {
  const last = Math.max(1, Math.ceil(result.total / result.page_size));
  return <div className="space-y-6">
      <OrderTable title="فهرست سفارش‌ها" orders={result.items} />
      <nav aria-label="صفحه‌بندی سفارش" className="flex items-center justify-end gap-3">
        {page <= 1 ? <Button variant="outline" size="sm" disabled>قبلی</Button> : <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${page - 1}`}>قبلی</Link></Button>}
        <span className="text-sm tabular text-muted-foreground">صفحه {page} از {last}</span>
        {page >= last ? <Button variant="outline" size="sm" disabled>بعدی</Button> : <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${page + 1}`}>بعدی</Link></Button>}
      </nav>
  </div>;
}
/** Retain the existing unpaid-request confirmation and decision handlers. */
export function ReviewQueueView({ queue }: { queue: ReviewOrder[] }) {
  return (
        <Card>
          <CardHeader><CardTitle>درخواست‌های نیازمند بررسی دستی</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {queue.map((order) => (
              <div key={order.id} className="grid items-start gap-4 rounded-lg border border-border p-4 lg:grid-cols-[1fr_1.4fr]">
                <div className="space-y-2">
                  <p className="text-sm font-semibold">سفارش #{order.id} · {order.platform === "bale" ? "بله" : "تلگرام"}</p>
                  <p className="text-xs text-muted-foreground">محصول #{order.product_id} · {formatOrderAmount(order)}</p>
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
  );
}
