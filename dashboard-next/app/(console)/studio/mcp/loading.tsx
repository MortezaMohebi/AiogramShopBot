import { ActivityIndicator } from "@/components/ui/activity-indicator";

/** Loading never implies an empty inventory or completed consent. */
export default function Loading() {
  return <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">
    <ActivityIndicator state="connecting" label="در حال دریافت اتصال‌ها و وضعیت دسترسی…" />
  </div>;
}
