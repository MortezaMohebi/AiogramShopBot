import { PageHeading } from "@/components/blocks/page-heading";
import { ChannelPerformance } from "@/components/blocks/channel-performance";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { adminFetch } from "@/lib/bridge";
import { formatIrr } from "@/lib/utils";
import type { Report } from "@/lib/types";
import Link from "next/link";

type Params = Promise<{ days?: string }>;

/** Server-rendered report; never mixes IRR, Stars and merchant credit. */
export default async function ReportsPage({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const allowed = [0, 7, 30, 90, 365];
  const days = Number(params.days ?? 30);
  const period = allowed.includes(days) ? days : 30;
  const report = await adminFetch<Report>(`/reports?days=${period}`);
  const periods = [{ n: 7, label: "۷ روز" }, { n: 30, label: "۳۰ روز" }, { n: 90, label: "۹۰ روز" }, { n: 365, label: "یک سال" }, { n: 0, label: "همه سوابق جدید" }];

  return (
    <div>
      <PageHeading title="گزارش‌های فروشگاه" description="مبالغ درگاه‌ها، اعتبار داخلی و Stars جداگانه محاسبه می‌شوند. سوابق قدیمی تلگرام در این گزارش نیست." />
      <div className="mb-6 flex flex-wrap gap-2">
        {periods.map(({ n, label }) => (
          <Link key={n} href={`/reports?days=${n}`}
            aria-current={period === n ? "page" : undefined}
            className={`rounded-lg border px-4 py-2 text-sm transition-colors ${period === n ? "border-primary bg-accent text-accent-foreground" : "border-border hover:bg-muted"}`}>
            {label}
          </Link>
        ))}
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <ChannelPerformance channels={report.channels}
          periodLabel={period === 0 ? "همهٔ سوابق موجود" : `${period.toLocaleString("fa-IR")} روز گذشته`} />
        <Card>
          <CardHeader><CardTitle>دفترکل و تسویه</CardTitle></CardHeader>
          <CardContent className="space-y-5 text-sm">
            <div className="flex justify-between border-b border-border pb-3"><span className="text-muted-foreground">افزایش اعتبار داخلی</span><b>{formatIrr(report.credit_issued_irr)}</b></div>
            <div className="flex justify-between border-b border-border pb-3"><span className="text-muted-foreground">کسر اعتبار داخلی</span><b>{formatIrr(report.credit_spent_irr)}</b></div>
            <div className="flex justify-between border-b border-border pb-3"><span className="text-muted-foreground">پرونده بازپرداخت باز</span><b>{report.open_refund_cases}</b></div>
            <div className="flex justify-between"><span className="text-muted-foreground">ارسال نامشخص کمپین</span><b>{report.campaigns.unknown}</b></div>
            <p className="text-xs leading-6 text-muted-foreground">برای تسویه، تراکنش‌ها را با گزارش بانک یا ارائه‌دهندهٔ پرداخت تطبیق دهید.</p>
          </CardContent>
        </Card>
      </div>
      <Card className="mt-5">
        <CardHeader><CardTitle>محصولات پرفروش</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>نام محصول</TableHead><TableHead>شناسه</TableHead><TableHead>تعداد پرداخت‌شده</TableHead></TableRow></TableHeader>
            <TableBody>
              {report.top_products.map((item) => (
                <TableRow key={item.product_id}>
                  <TableCell className="font-medium">{item.name}</TableCell>
                  <TableCell>#{item.product_id}</TableCell>
                  <TableCell className="tabular">{item.quantity}</TableCell>
                </TableRow>
              ))}
              {!report.top_products.length ? <TableRow><TableCell colSpan={3} className="py-10 text-center text-muted-foreground">فروش تأییدشده‌ای وجود ندارد.</TableCell></TableRow> : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
