import Link from "next/link";
import { ArrowUpLeft, Megaphone, ShieldCheck } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { SectionCards } from "@/components/blocks/section-cards";
import { ChannelPerformance } from "@/components/blocks/channel-performance";
import { OrderTable } from "@/components/blocks/order-table";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { adminFetch } from "@/lib/bridge";
import type { Overview } from "@/lib/types";

/** Real dashboard-01 composition; all KPIs originate from FastAPI/PostgreSQL. */
export default async function DashboardPage() {
  const overview = await adminFetch<Overview>("/overview");
  const queued = overview.campaigns.queued ?? 0;
  const unknown = overview.campaigns.unknown ?? 0;

  return (
    <div>
      <PageHeading
        title="نمای کلی فروشگاه"
        description="وضعیت دو پیام‌رسان، فروشگاه و کمپین‌ها در یک نگاه؛ اعداد مستقیماً از پایگاه داده خوانده می‌شوند."
        action={
          <Button asChild variant="outline">
            <Link href="/reports">مشاهده گزارش‌ها <ArrowUpLeft /></Link>
          </Button>
        }
      />
      <SectionCards overview={overview} />
      <div className="my-6 grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <ChannelPerformance channels={overview.channels} />
        <Card>
          <CardHeader>
            <div className="mb-2 flex size-10 items-center justify-center rounded-lg bg-accent text-primary">
              <Megaphone className="size-5" />
            </div>
            <CardTitle>وضعیت Broadcast</CardTitle>
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
    </div>
  );
}
