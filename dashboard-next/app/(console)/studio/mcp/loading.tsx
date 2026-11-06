/** Loading never implies an empty inventory or completed consent. */
export default function Loading() {
  return <p role="status" className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">در حال دریافت اتصال‌ها و وضعیت دسترسی…</p>;
}
