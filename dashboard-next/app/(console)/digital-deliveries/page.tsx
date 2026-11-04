import { notFound } from "next/navigation";
import Link from "next/link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { adminFetch, currentStaff } from "@/lib/bridge";

type Query = Promise<{ status?: string }>;
type Receipt = {
  id: string; store_id: string; bot_id: string;
  order_id: number; product_id: number;
  kind: "file" | "license"; status: string;
  provider_message_id: string | null;
  failure_code: string | null;
  delivered_at: string | null;
};

const STATES = ["all", "queued", "sending", "delivered", "needs_review", "blocked"];

/** Digital delivery receipts exclude license plaintext and storage secrets. */
export default async function DigitalReceipts({
  searchParams,
}: { searchParams: Query }) {
  const staff = await currentStaff();
  if (!["superadmin", "sales", "finance"].includes(staff.role)) notFound();
  const query = await searchParams;
  const status = STATES.includes(query.status ?? "") ? query.status ?? "all" : "all";
  const data = await adminFetch<{
    items: Receipt[]; automatic_retries: boolean;
  }>(status === "all" ? "/digital-deliveries" : `/digital-deliveries?status=${status}`);
  return <div className="space-y-5">
    <PageHeading title="تحویل امن محصولات دیجیتال"
      description="رسید ارسال فایل/لایسنس بر اساس Message ID معتبر؛ حالت نامشخص خودکار تکرار نمی‌شود." />
    <div className="flex flex-wrap gap-2">
      {STATES.map(item => <Button key={item} asChild size="sm"
        variant={status === item ? "secondary" : "outline"}>
        <Link href={item === "all" ? "/digital-deliveries"
          : `/digital-deliveries?status=${item}`}>
          {item}
        </Link>
      </Button>)}
    </div>
    <Card>
      <CardHeader><CardTitle>سوابق تحویل ({data.items.length})</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {data.items.map(item =>
          <article key={item.id} className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <strong>سفارش #{item.order_id} · محصول #{item.product_id}</strong>
              <span>{item.status}</span>
            </div>
            <p>نوع: {item.kind === "file" ? "فایل" : "لایسنس"}</p>
            <p dir="ltr" className="text-xs text-muted-foreground break-all">
              Store {item.store_id.slice(0, 8)} · Bot {item.bot_id.slice(0, 8)}
            </p>
            <p className="text-xs text-muted-foreground">
              رسید پیام‌رسان: {item.provider_message_id ?? "ثبت نشده"} ·
              علت توقف: {item.failure_code ?? "—"}
            </p>
          </article>)}
        {!data.items.length ? <p className="text-sm text-muted-foreground">
          در این وضعیت هنوز رکورد تحویل وجود ندارد.
        </p> : null}
      </CardContent>
    </Card>
  </div>;
}
