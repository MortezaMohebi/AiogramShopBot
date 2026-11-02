import { Card, CardContent } from "@/components/ui/card";

/** Semantic skeleton while real server-side data loads. */
export default function DashboardLoading() {
  return (
    <div aria-busy="true" aria-label="در حال بارگذاری اطلاعات فروشگاه" className="space-y-6 animate-pulse">
      <div className="space-y-3">
        <div className="h-9 w-56 rounded-lg bg-muted" />
        <div className="h-4 w-80 max-w-full rounded bg-muted" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
      <div className="h-64 rounded-xl border border-border bg-card" />
    </div>
  );
}
