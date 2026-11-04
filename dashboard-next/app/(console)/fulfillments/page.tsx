import Link from "next/link";
import { PageHeading } from "@/components/blocks/page-heading";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { ShipmentRecord } from "@/lib/customer-experience";
import { advanceFulfillment } from "./actions";

type Query = Promise<{ saved?: string; error?: string }>;

/** Customer fulfillment events are a separate ledger from payment settlement. */
export default async function FulfillmentsPage({
  searchParams,
}: { searchParams: Query }) {
  const [records, user, query] = await Promise.all([
    adminFetch<{ items: ShipmentRecord[] }>("/fulfillments"),
    currentStaff(), searchParams,
  ]);
  const canEdit = ["superadmin", "sales"].includes(user.role);
  return <div className="space-y-5">
    <PageHeading title="آماده‌سازی و ارسال سفارش‌ها"
      description="ثبت مراحل انجام فقط برای سفارش‌های با پرداخت تأییدشده؛ تحویل دیجیتال تنها پس از تأیید پرداخت و ثبت رسید ارسال انجام می‌شود." />
    {query.saved ? <p role="status" className="rounded-lg border p-3 text-sm">
      مرحله انجام سفارش ثبت شد؛ وضعیت مالی تغییر نکرد.
    </p> : null}
    {query.error ? <p role="alert" className="rounded-lg border border-destructive p-3 text-sm text-destructive">
      مرحله ثبت نشد؛ وضعیت فعلی، Store جاری یا کد رهگیری را بررسی کنید.
    </p> : null}
    <div className="grid gap-4 xl:grid-cols-2">
      {records.items.map(order => <Card key={order.order_id}>
        <CardHeader><CardTitle>سفارش #{order.order_id}</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p>Store: <span dir="ltr">{order.store_id}</span></p>
          <p>وضعیت انجام: <strong>{order.status}</strong></p>
          <p>نوع: {order.kind ?? "تعیین‌نشده"} · مبلغ: {order.total_irr} IRR</p>
          {order.tracking_code ? <p>مرجع رهگیری: {order.tracking_code} / {order.carrier}</p> : null}
          {order.kind === "digital" ? <p className="rounded-lg border p-3 text-sm text-muted-foreground">
            تحویل فایل یا لایسنس از صف امن انجام می‌شود و رسید آن جداگانه ثبت می‌شود.
            <Link href="/digital-deliveries" className="ms-1 underline underline-offset-4">مشاهدهٔ رسید تحویل</Link>
          </p> : null}
          {canEdit && order.kind !== "digital" && order.status !== "delivered"
            ? <form action={advanceFulfillment}
            className="space-y-3 rounded-lg border p-3">
            <input type="hidden" name="order_id" value={order.order_id} />
            <input type="hidden" name="expected_version" value={order.version} />
            <label className="block space-y-2">مرحلهٔ بعد
              <select name="next_status" required
                defaultValue={order.status === "ready" ? "shipped" :
                  order.status === "shipped" ? "delivered" : "ready"}
                className="block h-10 w-full rounded-md border bg-background px-3">
                {(order.status === "processing" || order.status === "not_started")
                  ? <option value="ready">آماده‌شده</option> : null}
                {order.status === "ready" ?
                  <option value="shipped">تحویل به حمل‌کننده</option> : null}
                {order.status === "shipped" ?
                  <option value="delivered">تکمیل انجام سفارش</option> : null}
              </select>
            </label>
            <>
              <label className="block space-y-2">نام شرکت حمل در مرحله ارسال
                <Input name="carrier" maxLength={80} placeholder="شرکت حمل" />
              </label>
              <label className="block space-y-2">کد رهگیری
                <Input name="tracking_code" maxLength={120} placeholder="کد واقعی، نه ساختگی" />
              </label>
            </>
            <Button type="submit" variant="outline">ثبت مرحله</Button>
          </form> : null}
        </CardContent>
      </Card>)}
    </div>
    {!records.items.length ? <p className="text-sm text-muted-foreground">
      هنوز سفارش پرداخت‌شده‌ای برای انجام وجود ندارد.
    </p> : null}
  </div>;
}
