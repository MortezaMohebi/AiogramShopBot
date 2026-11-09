import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";

const number = new Intl.NumberFormat("fa-IR");

/** A top-level list pager. The range describes actual rows on the current page. */
export function ListRangePager({ start, end, total, previous, next, label }: {
  start: number;
  end: number;
  total: number;
  previous?: string;
  next?: string;
  label: string;
}) {
  return <nav aria-label={label} className="flex min-h-9 flex-wrap items-center gap-2 self-end justify-self-end">
    <span dir="ltr" className="whitespace-nowrap text-sm tabular-nums">
      <span className="sr-only">ردیف‌های </span>
      {start === end ? number.format(end) : `${number.format(start)}–${number.format(end)}`}
      <span aria-hidden="true"> / </span><span className="sr-only"> از </span>{number.format(total)}
    </span>
    <div className="flex">
      {previous ? <Button asChild size="icon" variant="outline" className="size-9 rounded-e-none">
        <Link href={previous} aria-label="صفحهٔ قبلی" title="صفحهٔ قبلی"><ChevronRight aria-hidden="true" /></Link>
      </Button> : <Button type="button" size="icon" variant="outline" className="size-9 rounded-e-none"
        aria-label="صفحهٔ قبلی" disabled><ChevronRight aria-hidden="true" /></Button>}
      {next ? <Button asChild size="icon" variant="outline" className="size-9 rounded-s-none border-s-0">
        <Link href={next} aria-label="صفحهٔ بعدی" title="صفحهٔ بعدی"><ChevronLeft aria-hidden="true" /></Link>
      </Button> : <Button type="button" size="icon" variant="outline" className="size-9 rounded-s-none border-s-0"
        aria-label="صفحهٔ بعدی" disabled><ChevronLeft aria-hidden="true" /></Button>}
    </div>
  </nav>;
}
