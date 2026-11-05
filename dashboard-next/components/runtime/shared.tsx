import Link from "next/link";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { deliveryState, runLabels } from "@/lib/runtime/state";
/** Operational identifiers are isolated from surrounding Persian text. */
export function RuntimeId({
  children
}: {
  children: ReactNode;
}) {
  return <bdi dir="ltr" className="break-all font-mono text-[11px]">
  {children ?? "—"}
</bdi>;
}
export function RuntimeDate({
  value
}: {
  value: string;
}) {
  return <time dateTime={value}>
  {new Date(value).toLocaleString("fa-IR", {
      timeZone: "Asia/Tehran"
    })}
</time>;
}
export function RuntimeStatus({
  status,
  delivery = false
}: {
  status: string;
  delivery?: boolean;
}) {
  const danger = ["failed", "uncertain", "dead_letter"].includes(status),
    success = ["completed", "sent", "succeeded"].includes(status);
  return <Badge tone={danger ? "danger" : success ? "success" : "neutral"}>
  {delivery ? deliveryState(status) : runLabels[status] ?? {
      succeeded: "انجام‌شده",
      pending: "در صف",
      uncertain: "نتیجه نامعلوم",
      running: "در حال اجرا",
      cancelled: "لغوشده"
    }[status] ?? status}
</Badge>;
}
export function RuntimeEmpty({
  children
}: {
  children: ReactNode;
}) {
  return <p className="rounded-lg border border-dashed p-8 text-center text-sm leading-7 text-muted-foreground">
  {children}
</p>;
}
export function RuntimePanel({
  title,
  children
}: {
  title: string;
  children: ReactNode;
}) {
  return <section className="min-w-0 space-y-4 rounded-xl border bg-card p-4 sm:p-5">
  <h2 className="text-base font-semibold">
    {title}
  </h2>
  {children}
</section>;
}
export function RuntimePager({
  page,
  hasMore,
  href
}: {
  page: number;
  hasMore: boolean;
  href: (page: number) => string;
}) {
  return <nav aria-label="صفحه‌بندی Runtime" className="mt-5 flex flex-wrap items-center justify-between gap-4 text-sm">
  <span>صفحهٔ {page.toLocaleString("fa-IR")}</span>
  <div className="flex gap-5">
    {page > 1 && <Link className="text-primary hover:underline" href={href(page - 1)}>قبلی</Link>}
    {hasMore && <Link className="text-primary hover:underline" href={href(page + 1)}>بعدی</Link>}
  </div>
</nav>;
}
