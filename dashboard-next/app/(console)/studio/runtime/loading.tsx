import { ActivityIndicator } from "@/components/ui/activity-indicator";

/** Unavailable data is never presented as zero. */
export default function Loading() {
  return <div className="space-y-5">
  <ActivityIndicator label="در حال دریافت وضعیت اجرا فروشگاه…" className="text-sm text-muted-foreground" />
  <div aria-hidden="true" className="h-12 rounded-xl bg-muted" />
  <div aria-hidden="true" className="h-80 rounded-xl border bg-muted/40" />
</div>;
}
