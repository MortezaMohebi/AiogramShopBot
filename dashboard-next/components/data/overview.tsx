import Link from "next/link";
import { Megaphone, ShieldCheck } from "lucide-react";
import { SectionCards } from "@/components/blocks/section-cards";
import { ChannelPerformance } from "@/components/blocks/channel-performance";
import { OrderTable } from "@/components/blocks/order-table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { readSection } from "@/lib/read-section";
import type { Overview } from "@/lib/types";
import { DataSectionError } from "./section-error";
/** The overview endpoint remains the sole source of dashboard metrics. */
export async function OverviewSection() {
  const result = await readSection<Overview>("/overview");
  if (!result.ok) return <DataSectionError title="نمای کلی دریافت نشد" />;
  return <OverviewView overview={result.data} />;
}
export function OverviewView({ overview }: { overview: Overview }) {
  const queued = overview.campaigns.queued ?? 0;
  const unknown = overview.campaigns.unknown ?? 0;
  return <>
      <SectionCards overview={overview} />
      <div className="my-6 grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <ChannelPerformance channels={overview.channels} />
        <Card>
          <CardHeader>
            <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-accent text-primary">
              <Megaphone className="size-5" />
            </div>
            <CardTitle>ارسال پیام‌های گروهی</CardTitle>
            <CardDescription>فقط به مشتریانی که دریافت اطلاعیه را پذیرفته‌اند.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="flex justify-between border-b border-border pb-3 text-sm">
              <span className="text-muted-foreground">پیام‌های در صف</span>
              <strong className="tabular">{queued}</strong>
            </div>
            <div className="flex justify-between border-b border-border pb-3 text-sm">
              <span className="text-muted-foreground">تحویل نامشخص</span>
              <strong className="tabular">{unknown}</strong>
            </div>
            <p className="flex gap-2 text-xs leading-7 text-muted-foreground">
              <ShieldCheck className="mt-1 size-4 shrink-0 text-primary" />
              پیام‌های نامشخص خودکار دوباره ارسال نمی‌شوند.
            </p>
            <Button asChild variant="secondary" className="w-full">
              <Link href="/campaigns">مدیریت کمپین‌ها</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
      <OrderTable orders={overview.recent_orders} />
  </>;
}
