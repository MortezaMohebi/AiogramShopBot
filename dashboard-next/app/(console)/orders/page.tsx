import { Suspense } from "react";
import { notFound } from "next/navigation";
import Link from "next/link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { currentStaff } from "@/lib/bridge";
import { OrdersResults, ReviewQueue } from "@/components/data/orders";
import { TableSkeleton, FormSkeleton } from "@/components/data/skeletons";
type Params = Promise<{ page?: string; saved?: string; error?: string }>;

/** Authorization precedes streaming; the queue remains restricted to sales managers. */
export default async function OrdersPage({ searchParams }: { searchParams: Params }) {
  const [params, staff] = await Promise.all([searchParams, currentStaff()]);
  if (!["superadmin", "sales", "finance"].includes(staff.role)) notFound();
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.page ?? "1", 10) || 1));
  return (
    <div className="space-y-6">
      <PageHeading title="سفارش‌ها" description="درخواست‌های پیش از پرداخت را بررسی کنید. تأیید درخواست به معنای تأیید پرداخت نیست." />
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="outline" size="sm">
          <Link href="/data-models/orders">جست‌وجوی پیشرفته و خروجی سفارش‌ها</Link>
        </Button>
      </div>
      {params.saved ? <p role="status" className="rounded-lg bg-accent p-3 text-sm">تصمیم مدیر در سوابق سفارش ثبت شد.</p> : null}
      {params.error ? <p role="alert" className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">تصمیم انجام نشد. وضعیت سفارش، موجودی کالای منتشرشده و عبارت تأیید را بررسی کنید.</p> : null}
      {["superadmin", "sales"].includes(staff.role) ? (
        <Suspense key={`review-${page}`} fallback={<FormSkeleton label="در حال دریافت درخواست‌ها…" />}>
          <ReviewQueue />
        </Suspense>
      ) : null}
      <Suspense key={`orders-${page}`} fallback={<TableSkeleton label="در حال دریافت سفارش‌ها…" />}>
        <OrdersResults page={page} />
      </Suspense>
    </div>
  );
}
