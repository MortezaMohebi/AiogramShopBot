import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatIrr } from "@/lib/utils";
import type { ChannelStats } from "@/lib/types";

const labels: Record<string, string> = { telegram: "تلگرام", bale: "بله" };

/** Compact, accessible comparison; no invented chart points or exchange rates. */
export function ChannelPerformance({
  channels,
  periodLabel = "۳۰ روز گذشته",
}: { channels: ChannelStats[]; periodLabel?: string }) {
  const max = Math.max(1, ...channels.map((channel) => channel.orders));
  return (
    <Card>
      <CardHeader>
        <CardTitle>عملکرد پیام‌رسان‌ها</CardTitle>
        <CardDescription>سفارش‌های {periodLabel}؛ مبلغ Stars جداست.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {channels.map((channel) => (
          <div key={channel.platform} className="space-y-3">
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="font-semibold">{labels[channel.platform] ?? channel.platform}</span>
              <span className="text-muted-foreground tabular">
                {new Intl.NumberFormat("fa-IR").format(channel.orders)} سفارش
              </span>
            </div>
            <div
              className="h-2.5 overflow-hidden rounded-full bg-muted"
              role="meter" aria-label={`تعداد سفارش‌های ${labels[channel.platform] ?? channel.platform}`}
              aria-valuemin={0} aria-valuemax={max} aria-valuenow={channel.orders}
            >
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${(channel.orders / max) * 100}%` }}
              />
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-muted-foreground">
              <span>درگاه ریالی: <b className="text-foreground">{formatIrr(channel.gross_paid_irr)}</b></span>
              <span>اعتبار داخلی: <b className="text-foreground">{formatIrr(channel.store_credit_irr)}</b></span>
              {channel.platform === "telegram" ? (
                <span>Stars: <b className="text-foreground tabular">{channel.telegram_stars_xtr}</b> XTR</span>
              ) : null}
            </div>
          </div>
        ))}
        {!channels.length ? <p className="text-sm text-muted-foreground">آماری برای این بازه ثبت نشده است.</p> : null}
      </CardContent>
    </Card>
  );
}
