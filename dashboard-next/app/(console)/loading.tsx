import { Card, CardContent } from "@/components/ui/card";
import { ActivityIndicator } from "@/components/ui/activity-indicator";

/** Semantic skeleton while real server-side data loads. */
export default function DashboardLoading() {
  return (
    <div className="space-y-6">
      <ActivityIndicator label="در حال دریافت اطلاعات فروشگاه…" className="text-sm text-muted-foreground" />
      <div aria-hidden="true" className="space-y-3">
        <div className="h-9 w-56 rounded-lg bg-muted" />
        <div className="h-4 w-80 max-w-full rounded bg-muted" />
      </div>
      <div aria-hidden="true" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Card key={index}>
            <CardContent className="space-y-5 pt-6">
              <div className="h-4 w-28 rounded bg-muted" />
              <div className="h-10 w-24 rounded bg-muted" />
              <div className="h-3 w-36 rounded bg-muted" />
            </CardContent>
          </Card>
        ))}
      </div>
      <div aria-hidden="true" className="h-64 rounded-xl border border-border bg-card" />
    </div>
  );
}
