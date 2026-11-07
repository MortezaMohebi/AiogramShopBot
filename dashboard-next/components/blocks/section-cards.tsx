import { Boxes, CheckCircle2, ClipboardList, ShieldAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { Overview } from "@/lib/types";

const icons = [Boxes, CheckCircle2, ClipboardList, ShieldAlert];

/** Dashboard-01 KPI block built entirely from live backend counts. */
export function SectionCards({ overview }: { overview: Overview }) {
  const totalOrders = overview.channels.reduce((sum, item) => sum + item.orders, 0);
  const metrics = [
    { label: "محصولات تعریف‌شده", value: overview.products },
    { label: "محصولات منتشرشده", value: overview.published_products },
    { label: "سفارش‌های ۳۰ روز گذشته", value: totalOrders },
    { label: "پرونده بازپرداخت باز", value: overview.open_refunds, note: "نیازمند بررسی مالی" },
  ];
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
      {metrics.map((item, i) => {
        const Icon = icons[i];
        return (
          <Card key={item.label}>
            <CardContent className="pt-5">
              <div className="mb-5 flex items-center justify-between">
                <p className="text-sm text-muted-foreground">{item.label}</p>
                <span className="grid size-9 place-items-center rounded-lg bg-accent text-accent-foreground">
                  <Icon aria-hidden="true" className="size-4.5" />
                </span>
              </div>
              <p className="tabular text-3xl font-extrabold tracking-tight">
                {new Intl.NumberFormat("fa-IR").format(item.value)}
              </p>
              {item.note ? <p className="mt-2 text-xs text-muted-foreground">{item.note}</p> : null}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
