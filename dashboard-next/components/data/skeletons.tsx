import { Card, CardContent } from "@/components/ui/card";

/** Decorative geometry shares the global reduced-motion and theme rules. */
function Bar({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-muted ${className}`} />;
}

/** Table-shaped placeholder with a single readable status, no fabricated rows. */
export function TableSkeleton({ label }: { label: string }) {
  return <div role="status" aria-label={label} className="min-w-0 space-y-4">
    <p className="text-sm text-muted-foreground">{label}</p>
    <div aria-hidden="true" className="overflow-x-auto rounded-lg border">
      <div className="min-w-[38rem]">
        {Array.from({ length: 6 }, (_, row) => <div key={row}
          className={`grid grid-cols-6 gap-5 border-b p-4 last:border-0 ${row === 0 ? "bg-muted/30" : ""}`}>
          {Array.from({ length: 6 }, (_, column) => <Bar key={column} className="h-4 w-full" />)}
        </div>)}
      </div>
    </div>
    <div aria-hidden="true" className="flex justify-between gap-5"><Bar className="h-5 w-28" /><Bar className="h-9 w-40" /></div>
  </div>;
}

/** Reusable loading form for the review queue and on-demand Studio panels. */
export function FormSkeleton({ label }: { label: string }) {
  return <div role="status" aria-label={label} className="min-w-0 space-y-5 rounded-xl border bg-card p-5">
    <p className="text-sm text-muted-foreground">{label}</p>
    <div aria-hidden="true" className="space-y-5">
      {Array.from({ length: 4 }, (_, index) => <div key={index} className="space-y-2"><Bar className="h-4 w-28" /><Bar className="h-10 w-full" /></div>)}
    </div>
  </div>;
}

/** Match the dashboard's metric grid and content areas while its one read waits. */
export function OverviewSkeleton() {
  return <div role="status" aria-label="در حال دریافت نمای کلی…" className="min-w-0 space-y-6">
    <p className="text-sm text-muted-foreground">در حال دریافت نمای کلی…</p>
    <div aria-hidden="true" className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-4">
      {Array.from({ length: 4 }, (_, index) => <Card key={index}><CardContent className="space-y-5 pt-5"><Bar className="h-5 w-40 max-w-full" /><Bar className="h-9 w-20" /><Bar className="h-4 w-28" /></CardContent></Card>)}
    </div>
    <div aria-hidden="true" className="grid gap-4 xl:grid-cols-[1.5fr_1fr]"><div className="space-y-8 rounded-xl border bg-card p-6"><Bar className="h-6 w-48 max-w-full" /><Bar className="h-20 w-full" /><Bar className="h-20 w-full" /></div><div className="space-y-6 rounded-xl border bg-card p-6"><Bar className="h-6 w-48 max-w-full" /><Bar className="h-20 w-full" /><Bar className="h-10 w-full" /></div></div>
    <div aria-hidden="true" className="space-y-4 rounded-xl border bg-card p-6"><Bar className="h-6 w-36" /><Bar className="h-44 w-full" /></div>
  </div>;
}
