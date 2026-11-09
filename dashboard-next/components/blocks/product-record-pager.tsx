"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, List } from "lucide-react";
import { Button } from "@/components/ui/button";
import { productEditHref, productsListHref, type ProductNavigation } from "@/lib/product-list-context";

const numbers = new Intl.NumberFormat("fa-IR");

export function ProductRecordPager({ navigation, search, actions }: {
  navigation: ProductNavigation | null;
  search: string;
  actions?: ReactNode;
}) {
  const previous = navigation?.previous_id;
  const next = navigation?.next_id;
  return <nav dir="rtl" aria-label="صفحه‌گردان محصولات" className="flex flex-wrap items-center justify-between gap-2">
    <div className="flex flex-wrap items-center gap-2">
      <Button asChild variant="outline" size="sm">
      <Link href={productsListHref(search, navigation?.page ?? 1)}>
        <List aria-hidden="true" /> بازگشت به فهرست
      </Link>
      </Button>
      {actions}
    </div>
    {navigation ? <div className="ms-auto flex items-center gap-2">
      <span className="whitespace-nowrap text-sm tabular-nums" dir="ltr">
        <span className="sr-only">موقعیت محصول </span>{numbers.format(navigation.position)}
        <span aria-hidden="true"> / </span><span className="sr-only"> از </span>{numbers.format(navigation.total)}
      </span>
      <div className="flex" aria-label="جابه‌جایی بین محصولات">
        {previous == null ? <Button type="button" size="icon" variant="outline" className="size-9 rounded-e-none"
          aria-label="محصول قبلی" title="محصول قبلی" disabled><ChevronRight aria-hidden="true" /></Button>
          : <Button asChild size="icon" variant="outline" className="size-9 rounded-e-none">
            <Link href={productEditHref(previous, search)} prefetch={false}
              aria-label="محصول قبلی" title="محصول قبلی"><ChevronRight aria-hidden="true" /></Link>
          </Button>}
        {next == null ? <Button type="button" size="icon" variant="outline" className="size-9 rounded-s-none border-s-0"
          aria-label="محصول بعدی" title="محصول بعدی" disabled><ChevronLeft aria-hidden="true" /></Button>
          : <Button asChild size="icon" variant="outline" className="size-9 rounded-s-none border-s-0">
            <Link href={productEditHref(next, search)} prefetch={false}
              aria-label="محصول بعدی" title="محصول بعدی"><ChevronLeft aria-hidden="true" /></Link>
          </Button>}
      </div>
    </div> : null}
  </nav>;
}
