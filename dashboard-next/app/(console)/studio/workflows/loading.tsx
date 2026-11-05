export default function Loading() {
  return (
    <div role="status" aria-live="polite" className="space-y-5">
      <p className="text-sm text-muted-foreground">
        در حال دریافت فرایندهای فروشگاه…
      </p>
      <div className="h-12 animate-pulse rounded-xl bg-muted" />
      <div className="h-80 animate-pulse rounded-xl border bg-muted/40" />
    </div>
  );
}
