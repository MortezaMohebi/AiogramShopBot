import { PageHeading } from "@/components/blocks/page-heading";
import { OrderTable } from "@/components/blocks/order-table";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { Order, Paginated } from "@/lib/types";
import Link from "next/link";

type Params = Promise<{ page?: string }>;

/** Read-only order ledger: no UI button can mark an invoice as paid. */
export default async function OrdersPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  const result = await adminFetch<Paginated<Order>>(`/orders?page=${page}`);
  const last = Math.max(1, Math.ceil(result.total / result.page_size));
  return (
    <div>
      <PageHeading title="سفارش‌ها" description="سوابق جدید هر دو پیام‌رسان با وضعیت واقعی پرداخت؛ سفارش‌های قدیمی تلگرام تا Migration جدا باقی می‌مانند." />
      <OrderTable title="فهرست سفارش‌های مشترک" orders={result.items} />
      <div className="mt-5 flex items-center justify-end gap-3">
        <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${Math.max(1, page - 1)}`} aria-disabled={page === 1}>قبلی</Link></Button>
        <span className="text-sm tabular text-muted-foreground">صفحه {page} از {last}</span>
        <Button asChild variant="outline" size="sm"><Link href={`/orders?page=${Math.min(last, page + 1)}`} aria-disabled={page === last}>بعدی</Link></Button>
      </div>
    </div>
  );
}
