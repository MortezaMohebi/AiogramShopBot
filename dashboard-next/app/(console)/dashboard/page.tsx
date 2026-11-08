import { Suspense } from "react";
import { OverviewSection } from "@/components/data/overview";
import { OverviewSkeleton } from "@/components/data/skeletons";
import Link from "next/link";
import { ArrowUpLeft } from "lucide-react";
import { PageHeading } from "@/components/blocks/page-heading";
import { Button } from "@/components/ui/button";
import { currentStaff } from "@/lib/bridge";

/** Real dashboard-01 composition; all KPIs originate from FastAPI/PostgreSQL. */
export default async function DashboardPage() {
  await currentStaff();

  return (
    <div>
      <PageHeading
        title="نمای کلی فروشگاه"
        action={
          <Button asChild variant="outline">
            <Link href="/reports">مشاهده گزارش‌ها <ArrowUpLeft /></Link>
          </Button>
        }
      />
      <Suspense fallback={<OverviewSkeleton />}>
        <OverviewSection />
      </Suspense>
    </div>
  );
}
