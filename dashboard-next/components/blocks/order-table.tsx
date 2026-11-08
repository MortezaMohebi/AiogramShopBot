import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatDate, statusLabel } from "@/lib/utils";
import { formatOrderAmount } from "@/lib/order-money";
import type { Order } from "@/lib/types";

function tone(status: string): "success" | "warning" | "neutral" | "danger" {
  if (status === "paid") return "success";
  if (status === "paid_unfulfilled") return "danger";
  if (status === "pending_payment" || status === "pending_review") return "warning";
  return "neutral";
}

/** One product-neutral order table reused on overview and sales pages. */
export function OrderTable({ orders, title = "آخرین سفارش‌ها" }: { orders: Order[]; title?: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>سفارش</TableHead>
              <TableHead>پیام‌رسان</TableHead>
              <TableHead>کالا</TableHead>
              <TableHead>مبلغ</TableHead>
              <TableHead>وضعیت</TableHead>
              <TableHead>تاریخ</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {orders.map((order) => (
              <TableRow key={order.id}>
                <TableCell className="font-semibold tabular">#{order.id}</TableCell>
                <TableCell>{order.platform === "bale" ? "بله" : "تلگرام"}</TableCell>
                <TableCell className="max-w-48 truncate" title={order.name}>{order.name}</TableCell>
                <TableCell className="whitespace-nowrap tabular">{formatOrderAmount(order)}</TableCell>
                <TableCell><Badge tone={tone(order.status)}>{statusLabel(order.status)}</Badge></TableCell>
                <TableCell className="whitespace-nowrap">{formatDate(order.created_at)}</TableCell>
              </TableRow>
            ))}
            {orders.length === 0 ? (
              <TableRow><TableCell colSpan={6} className="py-12 text-center text-muted-foreground">هنوز سفارشی ثبت نشده است.</TableCell></TableRow>
            ) : null}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
