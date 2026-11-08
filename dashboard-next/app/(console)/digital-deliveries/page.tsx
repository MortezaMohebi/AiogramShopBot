import { ListSearch } from "@/components/blocks/search-tools";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
const STATE_LABELS: Record<string, string> = {
  all: "همه", queued: "در صف", sending: "در حال ارسال",
  delivered: "تحویل‌شده", needs_review: "نیازمند بررسی", blocked: "مسدودشده",
};

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
    <PageHeading title="تحویل محصولات دیجیتال"
      description="وضعیت تحویل فایل و لایسنس را بررسی کنید. ارسال با نتیجهٔ نامشخص خودکار تکرار نمی‌شود." />
    <ListSearch path="/digital-deliveries" values={{ status: { label: "وضعیت", value: status, inactive: "all", display: STATE_LABELS[status] } }}
      filters={<label className="block space-y-2 text-sm">وضعیت
        <select name="status" defaultValue={status} className="h-10 w-full rounded-md border border-input bg-background px-3">
          {STATES.map(item => <option key={item} value={item}>{STATE_LABELS[item]}</option>)}
        </select>
      </label>} />
    <Card>
      <CardHeader><CardTitle>سوابق تحویل ({data.items.length})</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {data.items.map(item =>
          <article key={item.id} className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap justify-between gap-2">
              <strong>سفارش #{item.order_id} · محصول #{item.product_id}</strong>
              <span>{STATE_LABELS[item.status] ?? item.status}</span>
            </div>
            <p>نوع: {item.kind === "file" ? "فایل" : "لایسنس"}</p>
            <p className="text-xs text-muted-foreground break-all">
              فروشگاه <bdi dir="ltr">{item.store_id.slice(0, 8)}</bdi> · ربات <bdi dir="ltr">{item.bot_id.slice(0, 8)}</bdi>
            </p>
            <p className="text-xs text-muted-foreground">
              رسید پیام‌رسان: <bdi dir="ltr">{item.provider_message_id ?? "ثبت نشده"}</bdi>
            </p>
            {item.failure_code ? <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer">اطلاعات پیگیری توقف</summary>
              <p dir="ltr" className="mt-1 break-all">{item.failure_code}</p>
            </details> : null}
          </article>)}
        {!data.items.length ? <p className="text-sm text-muted-foreground">
          در این وضعیت تحویلی ثبت نشده است.
        </p> : null}
      </CardContent>
    </Card>
  </div>;
}
