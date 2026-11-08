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
  const [data, addresses, wishlist] = await Promise.all([
    adminFetch<StoreCustomerDetail>(`/store-customers/${id}`),
    adminFetch<{
      customer_id: number;
      items: Array<{
        id: number;
        label: string;
        recipient: string;
        phone: string;
        city: string;
        province: string;
        full_address: string;
        postal_code: string | null;
        is_default: boolean;
      }>;
    }>(`/store-customers/${id}/addresses`),
    adminFetch<{
      customer_id: number;
      items: Array<{
        id: number; name: string; sku: string; is_published: boolean;
      }>;
    }>(`/store-customers/${id}/wishlist`),
  ]);
  return <div className="space-y-6">
    <Button asChild variant="outline" size="sm">
      <Link href="/store-customers">بازگشت به مشتریان</Link>
    </Button>
    <PageHeading title={data.customer.display_name || `مشتری #${id}`}
      description="اتصال حساب‌های پیام‌رسان فقط با تأیید هر دو حساب انجام می‌شود." />
    <Card>
      <CardHeader><CardTitle>هویت‌های ارتباطی تأییدشده</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {data.identities.map(identity =>
          <div key={identity.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3 text-sm">
            <span>{identity.platform === "bale" ? "بله" : "تلگرام"} · ربات <bdi dir="ltr">{identity.bot_id.slice(0, 8)}</bdi> · کاربر <bdi dir="ltr">{identity.platform_user_id}</bdi></span>
            <Button asChild variant="outline" size="sm">
              <Link href={`/customers/${identity.id}`}>پروندهٔ این حساب</Link>
            </Button>
          </div>)}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>دفتر اعتبار داخلی</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="leading-7 text-muted-foreground">
          اعتبار مستقل حساب‌های پیام‌رسان و اعتبار مشترک مشتری جداگانه نشان داده
          می‌شوند. این اعداد جمعِ قابل خرج‌کردن نیستند؛ انتقال اعتبار باید با سند
          مالی جدا و تأیید انجام شود.
        </p>
        {data.wallets.map(wallet =>
          <div key={wallet.id} className="flex justify-between gap-4 rounded-lg border p-3">
            <span>{wallet.scope === "customer" ? "اعتبار مشترک" : `اعتبار مستقل حساب #${wallet.identity_id}`}</span>
            <span dir="ltr">{wallet.balance_irr} IRR</span>
          </div>)}
        {!data.wallets.length ? <p>هنوز حساب اعتبار داخلی ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>نشانی‌های تأییدشدهٔ مشتری</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {addresses.items.map(address =>
          <div key={address.id} className="space-y-1 rounded-lg border p-3 text-sm">
            <div className="flex items-center justify-between gap-3">
              <strong>{address.label}</strong>
              {address.is_default ? <span className="text-xs text-muted-foreground">
                پیش‌فرض
              </span> : null}
            </div>
            <p>{address.province}، {address.city}، {address.full_address}</p>
            <p className="text-xs text-muted-foreground">
              گیرنده: {address.recipient} · تماس: {address.phone}
            </p>
          </div>)}
        {!addresses.items.length ?
          <p className="text-sm text-muted-foreground">مشتری هنوز نشانی‌ای ثبت نکرده است.</p>
          : null}
        <p className="text-xs text-muted-foreground">
          نشانی هر سفارش جداگانه نگهداری می‌شود؛ تغییر نشانی مشتری
          سفارش پرداخت‌شده را بازنویسی نمی‌کند.
        </p>
      </CardContent>
    </Card>
    <Card>
      <CardHeader><CardTitle>کالاهای علاقه‌مندی</CardTitle></CardHeader>
      <CardContent className="space-y-2">
        {wishlist.items.map(item =>
          <div key={item.id} className="flex items-center justify-between gap-3 border-b p-2 text-sm">
            <span>{item.name} · {item.sku || "بدون SKU"}</span>
            <span className="text-xs text-muted-foreground">
              {item.is_published ? "منتشرشده" : "منتشرنشده"}
            </span>
          </div>)}
        {!wishlist.items.length ?
          <p className="text-sm text-muted-foreground">مشتری محصولی ذخیره نکرده است.</p>
          : null}
      </CardContent>
    </Card>
  </div>;
}
