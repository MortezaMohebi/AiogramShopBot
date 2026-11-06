import { notFound } from "next/navigation";
import { saveShipping } from "@/app/(console)/shipping/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr } from "@/lib/utils";

type Shipping = {
  id: number; name: string; price_irr: string;
  position: number; is_active: boolean;
};

/** Native shipping CRUD, preserving past order's shipping cost snapshots. */
export default async function ShippingPage() {
  const [staff, shipping] = await Promise.all([
    currentStaff(),
    adminFetch<Shipping[]>("/shipping"),
  ]);
  if (!["superadmin", "sales"].includes(staff.role)) notFound();
  return (
    <div>
      <PageHeading title="روش‌های ارسال" description="برای خرید کالای فیزیکی، نشانی و روش ارسال الزامی است." />
      <div className="grid items-start gap-5 xl:grid-cols-[1fr_1.5fr]">
        <Card><CardHeader><CardTitle>افزودن روش ارسال</CardTitle></CardHeader><CardContent>
          <form action={saveShipping} className="space-y-4">
            <label className="block space-y-2 text-sm">نام روش
              <Input name="name" required maxLength={120} placeholder="عنوان روش ارسال" />
            </label>
            <label className="block space-y-2 text-sm">هزینه ارسال (ریال)
              <Input name="price_irr" dir="ltr" type="number" min={0} step={1} required defaultValue="0" />
            </label>
            <label className="block space-y-2 text-sm">ترتیب
              <Input name="position" type="number" min={0} defaultValue={0} required />
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" name="is_active" defaultChecked className="accent-primary" /> فعال
            </label>
            <Button type="submit">افزودن روش ارسال</Button>
          </form>
        </CardContent></Card>
        <Card><CardHeader><CardTitle>روش‌های تعریف‌شده</CardTitle></CardHeader><CardContent>
          <div className="divide-y divide-border">
            {shipping.map((item) => (
              <details key={item.id} className="py-4">
                <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
                  <strong>{item.name}</strong>
                  <div className="flex items-center gap-2">
                    <span className="text-sm tabular text-muted-foreground">{formatIrr(item.price_irr)}</span>
                    <Badge tone={item.is_active ? "success" : "neutral"}>{item.is_active ? "فعال" : "غیرفعال"}</Badge>
                  </div>
                </summary>
                <form action={saveShipping} className="mt-4 grid gap-3 rounded-lg bg-muted/60 p-4">
                  <input type="hidden" name="id" value={item.id} />
                  <label className="block space-y-2 text-sm">نام روش ارسال
                    <Input name="name" defaultValue={item.name} required maxLength={120} />
                  </label>
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="block space-y-2 text-sm">هزینه ارسال (ریال)
                      <Input name="price_irr" type="number" min={0} step={1} defaultValue={item.price_irr} dir="ltr" />
                    </label>
                    <label className="block space-y-2 text-sm">ترتیب
                      <Input name="position" type="number" min={0} defaultValue={item.position} dir="ltr" />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input type="checkbox" name="is_active" defaultChecked={item.is_active} className="accent-primary" /> فعال
                    </label>
                  </div>
                  <Button size="sm" type="submit">ذخیرهٔ تغییرات</Button>
                </form>
              </details>
            ))}
            {shipping.length === 0 ? <p className="py-8 text-center text-muted-foreground">هنوز روش ارسالی تعریف نشده است.</p> : null}
          </div>
        </CardContent></Card>
      </div>
    </div>
  );
}
