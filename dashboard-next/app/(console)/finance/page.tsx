import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr, statusLabel } from "@/lib/utils";

type Wallet = { user_id: string; platform: string; balance_irr: string };
type Refund = { id: number; order_id: number; platform: string; amount_irr: string; reason: string; status: string };

/** Read-only finance overview; payments and refunds never mutate via this page. */
export default async function FinancePage() {
  const staff = await currentStaff();
  if (!["superadmin", "finance"].includes(staff.role)) notFound();
  const [wallets, refunds] = await Promise.all([
    adminFetch<{items: Wallet[]; total: number}>("/wallets"),
    adminFetch<Refund[]>("/refunds"),
  ]);
  return (
    <div>
      <PageHeading title="امور مالی" description="اعتبار داخلی فروشگاه مستقل از کیف پول بله است؛ پرداخت، ثبت رسید و بازپرداخت فقط با سرویس مالی Python انجام می‌شوند." />
      <div className="grid gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>اعتبار داخلی مشتریان</CardTitle></CardHeader>
          <CardContent>
            <p className="mb-4 text-xs text-muted-foreground">تعداد کل حساب‌ها: {wallets.total} · ۱۰۰ حساب اخیر</p>
            <Table><TableHeader><TableRow><TableHead>پیام‌رسان</TableHead><TableHead>شناسه</TableHead><TableHead>موجودی</TableHead></TableRow></TableHeader>
              <TableBody>{wallets.items.map((item) => (
                <TableRow key={item.platform + item.user_id}>
                  <TableCell>{item.platform === "bale" ? "بله" : "تلگرام"}</TableCell>
                  <TableCell className="text-xs tabular">{item.user_id}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatIrr(item.balance_irr)}</TableCell>
                </TableRow>
              ))}
                {!wallets.items.length ? <TableRow><TableCell colSpan={3} className="py-8 text-center text-muted-foreground">حسابی ثبت نشده است.</TableCell></TableRow> : null}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>پرونده‌های بازپرداخت</CardTitle></CardHeader>
          <CardContent>
            <Table><TableHeader><TableRow><TableHead>سفارش</TableHead><TableHead>مبلغ</TableHead><TableHead>وضعیت</TableHead></TableRow></TableHeader>
              <TableBody>{refunds.map((refund) => (
                <TableRow key={refund.id}>
                  <TableCell>#{refund.order_id}</TableCell>
                  <TableCell className="whitespace-nowrap">{formatIrr(refund.amount_irr)}</TableCell>
                  <TableCell><Badge tone={refund.status === "confirmed" ? "success" : "warning"}>{statusLabel(refund.status)}</Badge></TableCell>
                </TableRow>
              ))}
                {!refunds.length ? <TableRow><TableCell colSpan={3} className="py-8 text-center text-muted-foreground">پرونده‌ای وجود ندارد.</TableCell></TableRow> : null}
              </TableBody>
            </Table>
            <p className="mt-5 text-xs leading-6 text-muted-foreground">اقدام مالی حساس، اصلاح اعتبار و Refund تا مهاجرت کامل در پنل SQLAdmin با تأیید مستقل مدیر باقی می‌مانند.</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
