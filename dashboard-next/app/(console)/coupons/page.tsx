import { notFound } from "next/navigation";
import { saveCoupon } from "@/app/(console)/coupons/actions";
import { PageHeading } from "@/components/blocks/page-heading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { adminFetch, currentStaff } from "@/lib/bridge";
import { formatIrr } from "@/lib/utils";

type Coupon = {
  id: number; code: string; discount_type: "fixed" | "percent";
  value: string; minimum_subtotal_irr: string; used_count: number;
  max_uses: number | null; expires_at: string | null; is_active: boolean;
};

/** Discount management without direct wallet/price manipulations. */
export default async function CouponsPage() {
  const [staff, coupons] = await Promise.all([
    currentStaff(),
    adminFetch<Coupon[]>("/coupons"),
  ]);
  if (!["superadmin", "marketing", "sales"].includes(staff.role)) notFound();
  const edit = ["superadmin", "marketing"].includes(staff.role);
  return (
    <div>
      <PageHeading title="کدهای تخفیف" />
      <div className="grid items-start gap-5 xl:grid-cols-[1fr_1.5fr]">
        {edit ? (
          <Card><CardHeader><CardTitle>کد تخفیف جدید</CardTitle></CardHeader><CardContent>
            <form action={saveCoupon} className="space-y-4">
              <label className="block space-y-2 text-sm">کد تخفیف (لاتین)
                <Input name="code" dir="ltr" minLength={3} maxLength={32} required placeholder="SAVE10" className="text-start" />
              </label>
              <label className="block space-y-2 text-sm">نوع
                <select name="discount_type" className="h-10 w-full rounded-md border border-input bg-background px-3">
                  <option value="percent">درصدی</option>
                  <option value="fixed">مبلغ ریالی</option>
                </select>
              </label>
              <label className="block space-y-2 text-sm">مقدار (درصد یا ریال)
                <Input name="value" type="number" min={1} step={1} defaultValue={10} required dir="ltr" />
              </label>
              <label className="block space-y-2 text-sm">حداقل مبلغ خرید (ریال)
                <Input name="minimum_subtotal_irr" type="number" min={0} step={1} defaultValue={0} dir="ltr" />
              </label>
              <label className="block space-y-2 text-sm">حداکثر دفعات استفاده
                <Input name="max_uses" type="number" min={1} step={1} placeholder="بدون سقف" dir="ltr" />
              </label>
              <label className="block space-y-2 text-sm">تاریخ انقضا (UTC)
                <Input name="expires_at" type="date" dir="ltr" />
              </label>
              <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="is_active" defaultChecked className="accent-primary" /> فعال</label>
              <Button type="submit">ایجاد کد تخفیف</Button>
            </form>
          </CardContent></Card>
        ) : null}
        <Card><CardHeader><CardTitle>کدهای تعریف‌شده</CardTitle></CardHeader><CardContent>
          <div className="divide-y divide-border">
            {coupons.map((coupon) => (
              <details key={coupon.id} className="py-4">
                <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3">
                  <strong dir="ltr">{coupon.code}</strong>
                  <div className="flex items-center gap-3 text-sm">
                    <span>{coupon.discount_type === "percent" ? `${coupon.value}٪` : formatIrr(coupon.value)}</span>
                    <Badge tone={coupon.is_active ? "success" : "neutral"}>{coupon.is_active ? "فعال" : "غیرفعال"}</Badge>
                  </div>
                </summary>
                <p className="mt-2 text-xs text-muted-foreground">استفاده: {coupon.used_count} / {coupon.max_uses ?? "نامحدود"} · حداقل خرید: {formatIrr(coupon.minimum_subtotal_irr)}</p>
                {edit ? (
                  <form action={saveCoupon} className="mt-3 grid gap-3 rounded-lg bg-muted/60 p-4 sm:grid-cols-2">
                    <input type="hidden" name="id" value={coupon.id} />
                    <label className="block space-y-2 text-sm">کد تخفیف
                      <Input name="code" defaultValue={coupon.code} required minLength={3} maxLength={32} dir="ltr" />
                    </label>
                    <label className="block space-y-2 text-sm">نوع تخفیف
                      <select name="discount_type" defaultValue={coupon.discount_type} className="h-10 w-full rounded-md border border-input bg-background px-3">
                        <option value="percent">درصدی</option><option value="fixed">ریالی</option>
                      </select>
                    </label>
                    <label className="block space-y-2 text-sm">مقدار (درصد یا ریال)
                      <Input name="value" type="number" defaultValue={coupon.value} min={1} step={1} required dir="ltr" />
                    </label>
                    <label className="block space-y-2 text-sm">حداقل مبلغ خرید (ریال)
                      <Input name="minimum_subtotal_irr" type="number" defaultValue={coupon.minimum_subtotal_irr} min={0} step={1} dir="ltr" />
                    </label>
                    <label className="block space-y-2 text-sm">حداکثر دفعات استفاده
                      <Input name="max_uses" type="number" defaultValue={coupon.max_uses ?? ""} min={1} step={1} placeholder="بدون سقف" dir="ltr" />
                    </label>
                    <label className="block space-y-2 text-sm">تاریخ انقضا (UTC)
                      <Input name="expires_at" type="date" defaultValue={coupon.expires_at?.slice(0, 10) ?? ""} dir="ltr" />
                    </label>
                    <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="is_active" defaultChecked={coupon.is_active} className="accent-primary" /> فعال</label>
                    <Button size="sm" type="submit">ذخیرهٔ تغییرات</Button>
                  </form>
                ) : null}
              </details>
            ))}
            {!coupons.length ? <p className="py-8 text-center text-muted-foreground">هنوز کد تخفیفی ثبت نشده است.</p> : null}
          </div>
        </CardContent></Card>
      </div>
    </div>
  );
}
