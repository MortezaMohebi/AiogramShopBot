import Link from "next/link";
import { notFound } from "next/navigation";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminFetch, currentStaff } from "@/lib/bridge";
import type { StoreCustomerDetail } from "@/lib/store-commerce";

type Params = Promise<{ id: string }>;

export default async function StoreCustomerPage({
  params,
}: { params: Params }) {
  const staff = await currentStaff();
  if (staff.role !== "superadmin") notFound();
  const { id } = await params;
  if (!/^[1-9][0-9]{0,17}$/.test(id)) notFound();
  const data = await adminFetch<StoreCustomerDetail>(`/store-customers/${id}`);
  return <div className="space-y-6">
    <Button asChild variant="outline" size="sm">
      <Link href="/store-customers">بازگشت به مشتریان</Link>
    </Button>
    <PageHeading title={data.customer.display_name || `مشتری #${id}`}
      description={`Store: ${data.customer.store_id} · هویت‌های متصل‌شده فقط با تأیید هر دو حساب`} />
    <Card>
      <CardHeader><CardTitle>هویت‌های ارتباطی تأییدشده</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {data.identities.map(identity =>
          <div key={identity.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
            <span>{identity.platform} · Bot {identity.bot_id.slice(0, 8)} · User {identity.platform_user_id}</span>
            <Button asChild variant="outline" size="sm">
              <Link href={`/customers/${identity.id}`}>CRM این هویت</Link>
            </Button>
          </div>)}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>دفتر اعتبار داخلی</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="leading-7 text-muted-foreground">
          موجودی‌های مستقل Identity و موجودی مشترک Customer به‌صورت جداگانه نشان داده
          می‌شوند. این اعداد جمعِ قابل خرج‌کردن نیستند؛ انتقال اعتبار باید با سند
          مالی جدا و تأیید انجام شود.
        </p>
        {data.wallets.map(wallet =>
          <div key={wallet.id} className="flex justify-between gap-4 rounded-lg border p-3">
            <span>{wallet.scope === "customer" ? "اعتبار مشترک" : `اعتبار مستقل Identity #${wallet.identity_id}`}</span>
            <span dir="ltr">{wallet.balance_irr} IRR</span>
          </div>)}
        {!data.wallets.length ? <p>هنوز حساب اعتبار داخلی ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
  </div>;
}
